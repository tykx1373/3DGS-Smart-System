// gpu_info.h - 显卡信息检测与智能分类
//
// 使用 DXGI 枚举系统显卡适配器，获取显卡名称，
// 并根据型号关键词智能分类为高性能独显/低功耗独显/核显，
// 同时给出推荐的渲染参数。
//
// 分类逻辑:
//   - NVIDIA RTX 30/40/50 系列 → 高性能独显
//   - NVIDIA GTX 系列           → 低功耗独显
//   - AMD RX 60/70 高端系列      → 高性能独显
//   - AMD RX 低端 / R 系列       → 低功耗独显
//   - Intel Arc                  → 低功耗独显
//   - Intel UHD / Iris / HD      → 核显
//   - 无法识别                    → 默认高性能（保守策略）
//
#pragma once
#include <string>
#include <algorithm>
#include <cctype>

// Windows API（WideCharToMultiByte）
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#ifndef NOMINMAX
#define NOMINMAX  // 防止 Windows 头文件定义 min/max 宏冲突
#endif
#include <windows.h>

// 自动链接 DXGI 库（MSVC）
#pragma comment(lib, "dxgi.lib")

#include <dxgi.h>

// ============================================================================
// 显卡检测结果
// ============================================================================
struct GpuInfo {
    std::string name;           // 显卡完整名称（如 "NVIDIA GeForce RTX 4090"）
    std::string shortName;      // 简短名称（用于 UI 显示，截断过长名称）
    GpuType     type;           // 智能分类结果
    bool        detected;       // 是否成功检测到显卡
    int         vramMB;         // 显存大小（MB，近似值，可能为 0）

    // 推荐的渲染参数
    int         recSampleStep;  // 推荐采样步长
    float       recSceneScale;  // 推荐场景缩放
    float       recBaseScale;   // 推荐高斯尺度
};

// ============================================================================
// 智能分类：根据显卡名称关键词判断类型
// ============================================================================
inline GpuType ClassifyGpu(const std::string& name) {
    // 转为小写进行关键词匹配
    std::string lower = name;
    std::transform(lower.begin(), lower.end(), lower.begin(),
        [](unsigned char c) { return (char)std::tolower(c); });

    // ---- Intel 核显检测 ----
    // "Intel(R) UHD Graphics", "Intel(R) Iris(R) Xe", "Intel(R) HD Graphics"
    if (lower.find("intel") != std::string::npos) {
        if (lower.find("arc") != std::string::npos) {
            // Intel Arc 独立显卡
            return GpuType::LowPower;
        }
        // 其他 Intel 均视为核显
        return GpuType::Integrated;
    }

    // ---- AMD 显卡检测 ----
    if (lower.find("amd") != std::string::npos ||
        lower.find("radeon") != std::string::npos ||
        lower.find("rx ") != std::string::npos) {

        // RX 70 系列 (如 RX 7900) → 高性能
        if (lower.find("rx 7") != std::string::npos) {
            return GpuType::HighPerf;
        }
        // RX 60 系列 (如 RX 6900 高端 → 高性能, RX 6400 低端 → 低功耗)
        if (lower.find("rx 6") != std::string::npos) {
            // 6800/6900/6950 为高端
            if (lower.find("6800") != std::string::npos ||
                lower.find("6900") != std::string::npos ||
                lower.find("6950") != std::string::npos) {
                return GpuType::HighPerf;
            }
            return GpuType::LowPower;
        }
        // RX 5 系列 → 低功耗
        if (lower.find("rx 5") != std::string::npos) {
            // Vega 系列例外
            if (lower.find("vega") != std::string::npos) {
                return GpuType::LowPower;
            }
            return GpuType::LowPower;
        }
        // 其他 AMD / Radeon → 低功耗
        return GpuType::LowPower;
    }

    // ---- NVIDIA 显卡检测 ----
    if (lower.find("nvidia") != std::string::npos ||
        lower.find("geforce") != std::string::npos ||
        lower.find("rtx") != std::string::npos ||
        lower.find("gtx") != std::string::npos) {

        // RTX 40 系列 → 高性能
        if (lower.find("rtx 4") != std::string::npos ||
            lower.find("rtx 5") != std::string::npos) {
            return GpuType::HighPerf;
        }
        // RTX 30 系列 → 高性能
        if (lower.find("rtx 3") != std::string::npos) {
            return GpuType::HighPerf;
        }
        // RTX 20 系列 → 低功耗（相对较老）
        if (lower.find("rtx 2") != std::string::npos) {
            return GpuType::LowPower;
        }
        // GTX 系列 → 低功耗
        if (lower.find("gtx") != std::string::npos) {
            return GpuType::LowPower;
        }
        // 其他 NVIDIA → 低功耗
        return GpuType::LowPower;
    }

    // ---- Microsoft Basic Render / 软件渲染 ----
    if (lower.find("microsoft") != std::string::npos ||
        lower.find("basic render") != std::string::npos) {
        return GpuType::Integrated;
    }

    // 无法识别 → 默认高性能（保守策略，让用户自行下调）
    return GpuType::HighPerf;
}

// ============================================================================
// 根据显卡类型生成推荐的渲染参数
// ============================================================================
inline void GetRecommendedParams(GpuType type, int& sampleStep, float& sceneScale, float& baseScale) {
    switch (type) {
        case GpuType::HighPerf:
            // 高性能独显：精细采样，高质量输出
            sampleStep  = 2;      // 每 2 像素采样一次（密集）
            sceneScale  = 2.0f;
            baseScale   = 0.3f;
            break;
        case GpuType::LowPower:
            // 低功耗独显：标准采样，平衡速度与质量
            sampleStep  = 4;      // 每 4 像素采样一次
            sceneScale  = 2.0f;
            baseScale   = 0.3f;
            break;
        case GpuType::Integrated:
            // 核显：稀疏采样，优先速度
            sampleStep  = 8;      // 每 8 像素采样一次
            sceneScale  = 1.5f;
            baseScale   = 0.4f;   // 稍大尺度补偿稀疏采样
            break;
    }
}

// ============================================================================
// 截断过长的显卡名称，用于 UI 显示
// ============================================================================
inline std::string TruncateGpuName(const std::string& name, size_t maxLen = 40) {
    if (name.size() <= maxLen) return name;
    return name.substr(0, maxLen - 3) + "...";
}

// ============================================================================
// 用 DXGI 检测系统显卡
//
// 枚举所有适配器，选择第一个非软件渲染的适配器（通常是主显卡）。
// 如果只有一个适配器，使用它。
// 返回 GpuInfo 结构，包含名称、类型和推荐参数。
// ============================================================================
inline GpuInfo DetectGpu() {
    GpuInfo info;
    info.detected = false;
    info.type = GpuType::HighPerf;  // 默认值
    info.vramMB = 0;

    IDXGIFactory* factory = nullptr;
    HRESULT hr = CreateDXGIFactory(__uuidof(IDXGIFactory), (void**)&factory);
    if (FAILED(hr) || factory == nullptr) {
        return info;
    }

    IDXGIAdapter* adapter = nullptr;
    std::string bestName;
    DXGI_ADAPTER_DESC bestDesc = {};

    // 枚举适配器，选择最佳的非软件适配器
    for (UINT i = 0; factory->EnumAdapters(i, &adapter) != DXGI_ERROR_NOT_FOUND; ++i) {
        DXGI_ADAPTER_DESC desc;
        if (SUCCEEDED(adapter->GetDesc(&desc))) {
            // 将 wchar_t 描述转换为 UTF-8 字符串
            // 使用 WideCharToMultiByte 正确处理 Unicode 字符
            char nameBuf[256] = {};
            WideCharToMultiByte(CP_UTF8, 0, desc.Description, -1,
                                nameBuf, sizeof(nameBuf), nullptr, nullptr);
            std::string name(nameBuf);

            std::string lower = name;
            std::transform(lower.begin(), lower.end(), lower.begin(),
                [](unsigned char c) { return (char)std::tolower(c); });

            bool isSoftware = (lower.find("microsoft basic render") != std::string::npos);

            if (!isSoftware) {
                bestName = name;
                bestDesc = desc;
                info.detected = true;
                adapter->Release();
                break;  // 使用第一个非软件适配器
            }
        }
        adapter->Release();
    }

    factory->Release();

    if (info.detected) {
        info.name = bestName;
        info.shortName = TruncateGpuName(bestName);
        info.vramMB = (int)(bestDesc.DedicatedVideoMemory / (1024 * 1024));
        info.type = ClassifyGpu(bestName);

        // 生成推荐参数
        GetRecommendedParams(info.type, info.recSampleStep, info.recSceneScale, info.recBaseScale);
    }

    return info;
}

// ============================================================================
// 获取显卡类型的显示名称
// ============================================================================
inline const char* GetGpuTypeName(GpuType type) {
    switch (type) {
        case GpuType::HighPerf:   return u8"高性能独显";
        case GpuType::LowPower:   return u8"低功耗独显";
        case GpuType::Integrated: return u8"核显";
        default:                  return u8"未知";
    }
}

// ============================================================================
// 获取显卡类型的算法描述
// ============================================================================
inline const char* GetGpuAlgoDesc(GpuType type) {
    switch (type) {
        case GpuType::HighPerf:
            return u8"高精度采样 (步长 2) + 完整 SH 计算\n适合最终质量输出";
        case GpuType::LowPower:
            return u8"标准采样 (步长 4) + DC 系数计算\n平衡速度与质量";
        case GpuType::Integrated:
            return u8"稀疏采样 (步长 8) + 仅 DC 系数\n快速预览用";
        default:
            return u8"";
    }
}
