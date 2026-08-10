// pipeline.h - 后台线程渲染管线，用于生成 3DGS 点
//
// 将导入的图片转换为 3D 高斯泼溅点云。管线在后台线程中运行，
// 保持 UI 响应，并支持取消操作。
//
// 管线流程:
//   1. Start() 启动后台线程，传入图片列表的副本
//   2. 对每张图片：以全分辨率重新加载，按 config.sampleStep 采样像素，
//      将 sRGB → 线性 → SH DC 转换，并为每个采样点创建 GaussianPoint
//   3. 打乱所有点（交错不同图片的点）
//   4. IsFinished() 返回 true 后，可通过 GetResult() 获取结果
//
// 当前实现说明:
//   这是一个"图片 → 点云"的几何映射，而非真正的 3DGS 训练。
//   缺少相机位姿、SfM 稀疏点云初始化和多图空间对齐。
//   每张图片被放置在不同的 Z 轴偏移位置。
//
// 高斯点格式 (62 个属性，与 PLY 兼容):
//   位置(3) + 法线(3) + SH DC(3) + SH rest(45) + 不透明度(1) +
//   尺度(3) + 旋转(4)
//
#pragma once
#include "image_manager.h"
#include <vector>
#include <atomic>
#include <thread>
#include <string>

// ============================================================================
// GPU 类型枚举
//
// 用户在设置中选择显卡类型，管线据此选择不同的算法路径：
//   HighPerf   - 高性能独立显卡（如 RTX 4090）：可用大并行度、高精度算法
//   LowPower   - 低功耗独立显卡（如 GTX 1050）：中等并行度，平衡精度与速度
//   Integrated - 核芯显卡（如 Intel UHD）：轻量算法，牺牲精度保速度
//
// 当前为空壳：管线暂未实际分派，仅记录用户选择并预留扩展点。
// ============================================================================
enum class GpuType {
    HighPerf    = 0,  // 高性能独显
    LowPower    = 1,  // 低功耗独显
    Integrated  = 2   // 核显
};

// 标准 3DGS 高斯点，包含 62 个属性（与 PLY 格式兼容）。
// 字段顺序与 PLY 顶点属性顺序一致，便于直接二进制导出。
struct GaussianPoint {
    // 世界空间位置
    float x, y, z;
    // 法线（3DGS 中通常为 0 - 不用于泼溅）
    float nx, ny, nz;
    // SH DC 系数（基础颜色，3 通道）
    // 转换公式: f_dc = linear_rgb * SH_C0  (SH_C0 = 0.28209479177387814)
    float f_dc_0, f_dc_1, f_dc_2;
    // SH rest 系数（45 个值，高阶球谐函数）
    // 当前置零 - 真正的 3DGS 优化会填充这些值
    float f_rest[45];
    // 不透明度（存储为原始值；标准 3DGS 使用 sigmoid logit）
    float opacity;
    // 尺度（3 轴，标准 3DGS 中以 log 空间存储）
    float scale_0, scale_1, scale_2;
    // 旋转四元数（单位四元数：单位旋转 = [1,0,0,0]）
    float rot_0, rot_1, rot_2, rot_3;
};

// 一次管线运行的结果，IsFinished() 返回 true 后可用。
struct RenderResult {
    std::vector<GaussianPoint> points;
    int  imageCount    = 0;       // 处理的源图片数量
    int  sourceWidth   = 0;       // 源图片最大宽度
    int  sourceHeight  = 0;       // 源图片最大高度
    bool completed     = false;   // 管线是否成功完成
};

// 管线运行配置。传递给 Pipeline::Start()。
struct PipelineConfig {
    int   sampleStep       = 4;       // 像素采样步长 (1=每个像素, 4=每4个像素)
    float pointSpacing     = 1.0f;    // 采样点在世界空间中的间距
    float sceneScale       = 2.0f;    // 整体场景缩放系数
    float baseOpacity      = 0.85f;   // 生成高斯点的基础不透明度
    float baseScale        = 0.3f;    // 生成高斯点的基础尺度
    bool  verbose          = true;    // 是否记录详细进度信息

    // GPU 类型扩展点：管线将根据显卡类型选择不同的算法路径。
    // 当前为空壳，Process() 中仅记录日志，尚未实际分派。
    //   HighPerf   - 高精度算法，大并行度
    //   LowPower   - 平衡算法，中等并行度
    //   Integrated - 轻量算法，优先速度
    GpuType gpuType         = GpuType::HighPerf;
};

class Pipeline {
public:
    Pipeline();
    ~Pipeline();

    // 在后台线程中启动管线。
    // 如果已在运行或未提供图片则返回 false。
    // images 向量按值复制以保证线程安全。
    bool Start(const std::vector<ImageEntry>& images, const PipelineConfig& config = PipelineConfig());

    // 停止管线（发出取消信号并等待后台线程结束）。
    void Stop();

    // 获取当前进度，范围 [0.0, 1.0]。
    float GetProgress() const { return m_progress.load(); }

    // 获取当前状态消息（用于 UI 显示）。
    std::string GetStatus() const { return m_status; }

    // 管线是否正在运行？
    bool IsRunning() const { return m_running.load(); }

    // 管线是否已结束（成功或已取消）？
    bool IsFinished() const { return m_finished.load(); }

    // 获取渲染结果（IsFinished() 返回 true 后有效）。
    const RenderResult& GetResult() const { return m_result; }

    // 重置状态以备新运行（清除进度、结果和状态）。
    void Reset();

private:
    std::thread             m_thread;
    std::atomic<float>      m_progress{0.0f};
    std::atomic<bool>       m_running{false};
    std::atomic<bool>       m_finished{false};
    std::atomic<bool>       m_cancel{false};
    std::string             m_status;      // 由 m_statusMutex 保护
    RenderResult            m_result;
    PipelineConfig          m_config;

    // 主处理函数（在后台线程中运行）。
    void Process(std::vector<ImageEntry> images);

    // 从单张图片生成高斯点。
    void ProcessImage(const ImageEntry& entry, int imageIndex, int totalImages,
                      std::vector<GaussianPoint>& outPoints);

    // 从单个像素采样创建一个高斯点。
    static GaussianPoint MakePoint(float x, float y, float z,
                                    unsigned char r, unsigned char g, unsigned char b,
                                    float scale, float opacity);
};
