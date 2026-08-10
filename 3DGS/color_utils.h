// color_utils.h - 3DGS 管线的色彩空间转换工具
//
// 提供在生成高斯泼溅点时所需的 sRGB、线性 RGB 与球谐函数 (SH) DC 系数
// 之间的相互转换。
//
// SH DC 系数关系:
//   f_dc = linear_color * SH_C0
// 其中 SH_C0 = 0.28209479177387814（零阶球谐基函数常量）
//
// 从 SH DC 还原线性颜色:  linear = f_dc / SH_C0
// 从线性还原 sRGB:        应用逆伽马编码
#pragma once
#include <cmath>

namespace ColorUtils {

// SH C0 常量：零阶球谐基函数值。
// 用于线性 RGB 与 SH DC 系数之间的相互转换。
constexpr float SH_C0 = 0.28209479177387814f;

// 将单个 sRGB 通道 [0, 255] 转换为线性 RGB [0, 1]。
// 使用标准 sRGB 传输函数 (IEC 61966-2-1)。
inline float sRGBToLinear(unsigned char srgbValue) {
    float cs = static_cast<float>(srgbValue) / 255.0f;
    if (cs <= 0.04045f) return cs / 12.92f;
    return std::pow((cs + 0.055f) / 1.055f, 2.4f);
}

// 将 sRGB [0, 255] 转换为 SH DC 系数。
inline float sRGBToSHDC(unsigned char srgbValue) {
    return sRGBToLinear(srgbValue) * SH_C0;
}

// 将线性 RGB [0, 1] 转换为 SH DC 系数。
inline float linearToSHDC(float linearValue) {
    return linearValue * SH_C0;
}

// 由 sRGB [0, 255] 三通道计算亮度 (Rec. 601 标准)。
inline float sRGBLuminance(unsigned char r, unsigned char g, unsigned char b) {
    return (0.299f * r + 0.587f * g + 0.114f * b) / 255.0f;
}

} // namespace ColorUtils
