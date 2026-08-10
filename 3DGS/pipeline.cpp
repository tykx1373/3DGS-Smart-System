// pipeline.cpp - 后台线程渲染管线的实现
//
// 公共 API 和设计说明见 pipeline.h。
//
// 线程安全:
//   - images 向量在 Start() 中按值复制，避免悬空引用
//   - m_status 由互斥锁保护 (statusMutex)
//   - m_progress、m_running、m_finished、m_cancel 为原子变量
//   - m_result 仅由后台线程写入，UI 在 IsFinished() 返回 true 后读取
//     （通过原子变量建立 happens-before 关系）
//
#include "pipeline.h"
#include "color_utils.h"
#include "log_system.h"

// 启用 stb_image 的 Windows UTF-8 路径支持（必须在使用 stbi_load 的编译单元中定义）
#define STBI_WINDOWS_UTF8
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

    // GPU 类型分派扩展点（当前为空壳，仅记录日志）
    // TODO: 根据 m_config.gpuType 选择不同的算法路径
    {
        const char* gpuNames[] = { u8"高性能独显", u8"低功耗独显", u8"核显" };
        const char* algoNames[] = { u8"高精度算法", u8"平衡算法", u8"轻量算法" };
        int gi = (int)m_config.gpuType;
        LogSystem::Info(std::string(u8"GPU 类型: ") + gpuNames[gi] +
                        u8" → 使用" + algoNames[gi]);
    }

    LogSystem::Info(u8"启动渲染管线: " + std::to_string(images.size()) + u8" 张图片, 采样步长=" +
                    std::to_string(m_config.sampleStep));

    // 启动后台线程（按值复制 images 向量以保证线程安全）
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
    allPoints.reserve((size_t)total * 1000); // 预估容量

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

    // 随机打乱，使不同图片的点交错分布。
    // 这有助于 3DGS 查看器渲染更均匀的点分布。
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

    // 位置
    p.x = x;  p.y = y;  p.z = z;
    // 法线（3DGS 中为零）
    p.nx = 0.0f;  p.ny = 0.0f;  p.nz = 0.0f;

    // 使用 ColorUtils 将 sRGB → 线性 → SH DC 系数转换。
    // SH DC = linear_color * SH_C0  (C0 球谐基函数常量)
    p.f_dc_0 = ColorUtils::sRGBToSHDC(r);
    p.f_dc_1 = ColorUtils::sRGBToSHDC(g);
    p.f_dc_2 = ColorUtils::sRGBToSHDC(b);

    // 高阶 SH 置零（真正的 3DGS 优化会填充这些值）
    for (int i = 0; i < 45; ++i) p.f_rest[i] = 0.0f;

    // 不透明度（若存储原始值则应用 sigmoid，当前存储最终值）
    p.opacity = opacity;

    // 尺度（log 空间，与 3DGS 存储方式一致）
    p.scale_0 = scale;
    p.scale_1 = scale;
    p.scale_2 = scale;

    // 单位旋转四元数
    p.rot_0 = 1.0f;
    p.rot_1 = 0.0f;
    p.rot_2 = 0.0f;
    p.rot_3 = 0.0f;

    return p;
}

void Pipeline::ProcessImage(const ImageEntry& entry, int imageIndex, int totalImages,
                            std::vector<GaussianPoint>& outPoints) {
    // 以全分辨率重新加载图片（纹理最大只有 512px）
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

    float sceneScale  = m_config.sceneScale;
    float spacing     = m_config.pointSpacing;
    float baseScale   = m_config.baseScale;
    float baseOpacity = m_config.baseOpacity;

    // 将图片在世界空间中以原点为中心
    float halfW = (float)w * 0.5f * spacing;
    float halfH = (float)h * 0.5f * spacing;

    // 每张图片按索引在 Z 轴上偏移（在图片间创建深度）
    float zOffset = ((float)imageIndex - (float)totalImages * 0.5f) * 0.5f;
    zOffset *= sceneScale;

    size_t pointsBefore = outPoints.size();

    // 采样像素并创建高斯点
    for (int y = 0; y < h; y += step) {
        for (int x = 0; x < w; x += step) {
            int idx = (y * w + x) * ch;
            unsigned char r = (ch >= 1) ? data[idx + 0] : 128;
            unsigned char g = (ch >= 2) ? data[idx + 1] : 128;
            unsigned char b = (ch >= 3) ? data[idx + 2] : 128;

            // 跳过接近黑色的像素（可能是背景）
            if (r + g + b < 30) continue;

            // 将像素坐标映射到世界空间（居中、缩放）
            float wx = ((float)x * spacing - halfW) * sceneScale / (float)std::max(w, h);
            float wy = (halfH - (float)y * spacing) * sceneScale / (float)std::max(w, h);
            float wz = zOffset;

            // 根据亮度添加轻微的逐像素尺度变化（增加视觉趣味）
            float lum = ColorUtils::sRGBLuminance(r, g, b);
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
