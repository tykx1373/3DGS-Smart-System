#include "pipeline.h"
#include "log_system.h"
#include "stb_image.h"
#include <cmath>
#include <algorithm>
#include <random>
#include <mutex>

Pipeline::Pipeline() {}
Pipeline::~Pipeline() {
    Stop();
}

bool Pipeline::Start(const std::vector<ImageEntry>& images, const PipelineConfig& config) {
    if (m_running.load()) {
        LogSystem::Warn(u8"管线已在运行中");
        return false;
    }
    if (images.empty()) {
        LogSystem::Error(u8"没有图片可处理");
        return false;
    }

    Reset();
    m_config = config;

    m_running.store(true);
    m_finished.store(false);
    m_cancel.store(false);
    m_progress.store(0.0f);
    m_status = u8"初始化渲染管线...";

    LogSystem::Info(u8"启动渲染管线: " + std::to_string(images.size()) + u8" 张图片, 采样步长=" +
                    std::to_string(m_config.sampleStep));

    // Launch background thread (copy images vector for thread safety)
    m_thread = std::thread(&Pipeline::Process, this, images);
    return true;
}

void Pipeline::Stop() {
    if (m_running.load()) {
        m_cancel.store(true);
        if (m_thread.joinable()) {
            m_thread.join();
        }
    } else if (m_thread.joinable()) {
        m_thread.join();
    }
    m_running.store(false);
}

void Pipeline::Reset() {
    if (m_running.load()) {
        LogSystem::Warn(u8"无法重置: 管线正在运行");
        return;
    }
    m_progress.store(0.0f);
    m_finished.store(false);
    m_cancel.store(false);
    m_status.clear();
    m_result = RenderResult();
}

void Pipeline::Process(std::vector<ImageEntry> images) {
    int total = (int)images.size();
    m_result.imageCount = total;

    std::vector<GaussianPoint> allPoints;
    allPoints.reserve((size_t)total * 1000); // Estimate

    static std::mutex statusMutex;

    for (int i = 0; i < total; ++i) {
        if (m_cancel.load()) {
            {
                std::lock_guard<std::mutex> lk(statusMutex);
                m_status = u8"已取消";
            }
            LogSystem::Warn(u8"渲染管线已取消");
            m_running.store(false);
            m_finished.store(true);
            return;
        }

        {
            std::lock_guard<std::mutex> lk(statusMutex);
            m_status = u8"处理图片 " + std::to_string(i + 1) + u8"/" + std::to_string(total) +
                       u8": " + images[i].fileName;
        }

        if (m_config.verbose) {
            LogSystem::Info(u8"管线 [" + std::to_string(i + 1) + u8"/" + std::to_string(total) +
                            u8"] 开始处理: " + images[i].fileName);
        }

        ProcessImage(images[i], i, total, allPoints);

        float progress = (float)(i + 1) / (float)total;
        m_progress.store(progress);
    }

    // Random shuffle so points from different images are interleaved
    std::mt19937 rng(42);
    std::shuffle(allPoints.begin(), allPoints.end(), rng);

    {
        std::lock_guard<std::mutex> lk(statusMutex);
        m_status = u8"完成，共生成 " + std::to_string(allPoints.size()) + u8" 个高斯点";
    }

    m_result.points = std::move(allPoints);
    m_result.completed = true;
    m_progress.store(1.0f);
    m_finished.store(true);
    m_running.store(false);

    LogSystem::Info(u8"渲染管线完成: 共生成 " + std::to_string(m_result.points.size()) + u8" 个高斯点");
}

GaussianPoint Pipeline::MakePoint(float x, float y, float z,
                                   unsigned char r, unsigned char g, unsigned char b,
                                   float scale, float opacity) {
    GaussianPoint p{};

    // Position
    p.x = x;  p.y = y;  p.z = z;
    // Normal (zero in 3DGS)
    p.nx = 0.0f;  p.ny = 0.0f;  p.nz = 0.0f;

    // Convert sRGB to linear, then to SH DC coefficients
    // SH DC = color * 0.28209479177387814 (C0 SH coefficient)
    const float SH_C0 = 0.28209479177387814f;
    auto sRGBToLinear = [](unsigned char c) -> float {
        float cs = (float)c / 255.0f;
        if (cs <= 0.04045f) return cs / 12.92f;
        return std::pow((cs + 0.055f) / 1.055f, 2.4f);
    };
    float lr = sRGBToLinear(r);
    float lg = sRGBToLinear(g);
    float lb = sRGBToLinear(b);
    p.f_dc_0 = lr * SH_C0;
    p.f_dc_1 = lg * SH_C0;
    p.f_dc_2 = lb * SH_C0;

    // Zero out higher-order SH
    for (int i = 0; i < 45; ++i) p.f_rest[i] = 0.0f;

    // Opacity (apply sigmoid if stored raw, but we store final value)
    p.opacity = opacity;

    // Scale (log-space, as 3DGS stores it)
    p.scale_0 = scale;
    p.scale_1 = scale;
    p.scale_2 = scale;

    // Identity rotation quaternion
    p.rot_0 = 1.0f;
    p.rot_1 = 0.0f;
    p.rot_2 = 0.0f;
    p.rot_3 = 0.0f;

    return p;
}

void Pipeline::ProcessImage(const ImageEntry& entry, int imageIndex, int totalImages,
                            std::vector<GaussianPoint>& outPoints) {
    // Reload image at full resolution (texture is only 512px max)
    int w, h, ch;
    unsigned char* data = stbi_load(entry.filePath.c_str(), &w, &h, &ch, 0);
    if (!data) {
        LogSystem::Error(u8"管线无法加载图片: " + entry.fileName + " (" + stbi_failure_reason() + ")");
        return;
    }

    if (m_config.verbose) {
        LogSystem::Info(u8"  分辨率: " + std::to_string(w) + "x" + std::to_string(h) +
                        u8", 通道: " + std::to_string(ch));
    }

    m_result.sourceWidth  = std::max(m_result.sourceWidth, w);
    m_result.sourceHeight = std::max(m_result.sourceHeight, h);

    int step = m_config.sampleStep;
    if (step < 1) step = 1;

    float sceneScale = m_config.sceneScale;
    float spacing    = m_config.pointSpacing;
    float baseScale  = m_config.baseScale;
    float baseOpacity = m_config.baseOpacity;

    // Center the image around origin in world space
    float halfW = (float)w * 0.5f * spacing;
    float halfH = (float)h * 0.5f * spacing;

    // Each image is offset along Z based on its index (creates depth between images)
    float zOffset = ((float)imageIndex - (float)totalImages * 0.5f) * 0.5f;
    zOffset *= sceneScale;

    size_t pointsBefore = outPoints.size();

    // Sample pixels and create Gaussian points
    for (int y = 0; y < h; y += step) {
        for (int x = 0; x < w; x += step) {
            int idx = (y * w + x) * ch;
            unsigned char r = (ch >= 1) ? data[idx + 0] : 128;
            unsigned char g = (ch >= 2) ? data[idx + 1] : 128;
            unsigned char b = (ch >= 3) ? data[idx + 2] : 128;

            // Skip near-black pixels (likely background)
            if (r + g + b < 30) continue;

            float wx = ((float)x * spacing - halfW) * sceneScale / (float)std::max(w, h);
            float wy = (halfH - (float)y * spacing) * sceneScale / (float)std::max(w, h);
            float wz = zOffset;

            // Slight per-pixel scale variation for visual interest
            float lum = (0.299f * r + 0.587f * g + 0.114f * b) / 255.0f;
            float pointScale = baseScale * (0.5f + lum * 0.5f);

            outPoints.push_back(MakePoint(wx, wy, wz, r, g, b, pointScale, baseOpacity));
        }
    }

    stbi_image_free(data);

    size_t added = outPoints.size() - pointsBefore;
    if (m_config.verbose) {
        LogSystem::Info(u8"  生成点数: " + std::to_string(added));
    }
}
