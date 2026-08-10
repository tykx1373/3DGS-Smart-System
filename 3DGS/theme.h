// theme.h - ImGui 主题管理：颜色、几何尺寸、强调色
//
// 提供:
//   - ApplyLightTheme() / ApplyDarkTheme(): 完整颜色调色板
//   - ApplyDynamicGeometry(): 随字体大小缩放的内边距/间距
//   - ApplyAccent(): 将强调色应用到交互控件
//   - GetAccentColor() / GetAccentName(): 5 种强调色预设
//
// 设计原则:
//   - 浅色主题使用柔和的哑光灰（非纯白）以减轻视觉疲劳
//   - 深色主题使用深石板色（非刺眼纯黑）以保证舒适的对比度
//   - 强调色默认为低饱和度的石板蓝，另有 4 种备选
//   - 几何尺寸随字体大小缩放，使按钮/框架按比例增长
//
#pragma once
#include <imgui.h>

// ---- 强调色预设 --------------------------------------------------------------
// 返回指定预设索引 (0..4) 的基础强调色 RGB 值。
inline ImVec4 GetAccentColor(int index) {
    switch (index) {
        case 1: return ImVec4(0.30f, 0.65f, 0.45f, 1.00f); // 翠绿
        case 2: return ImVec4(0.55f, 0.45f, 0.75f, 1.00f); // 紫罗兰
        case 3: return ImVec4(0.80f, 0.60f, 0.30f, 1.00f); // 琥珀
        case 4: return ImVec4(0.75f, 0.40f, 0.50f, 1.00f); // 玫红
        default: return ImVec4(0.48f, 0.58f, 0.68f, 1.00f);// 石板蓝 (default)
    }
}

inline const char* GetAccentName(int index) {
    switch (index) {
        case 1: return u8"翠绿";
        case 2: return u8"紫罗兰";
        case 3: return u8"琥珀";
        case 4: return u8"玫红";
        default: return u8"石板蓝";
    }
}

// 将强调色应用到交互控件（复选框、滑块、标题等）。
// 在 ApplyLightTheme()/ApplyDarkTheme() 之后调用。每帧调用安全。
inline void ApplyAccent(int index) {
    ImVec4 a = GetAccentColor(index);
    ImGuiStyle& style = ImGui::GetStyle();
    ImVec4* c = style.Colors;
    c[ImGuiCol_CheckMark          ] = ImVec4(a.x, a.y, a.z, 1.00f);
    c[ImGuiCol_SliderGrab         ] = ImVec4(a.x, a.y, a.z, 0.85f);
    c[ImGuiCol_SliderGrabActive   ] = ImVec4(a.x * 0.85f, a.y * 0.85f, a.z * 0.85f, 1.00f);
    c[ImGuiCol_Header             ] = ImVec4(a.x, a.y, a.z, 0.70f);
    c[ImGuiCol_HeaderHovered      ] = ImVec4(a.x, a.y, a.z, 0.50f);
    c[ImGuiCol_HeaderActive       ] = ImVec4(a.x * 0.85f, a.y * 0.85f, a.z * 0.85f, 0.90f);
    c[ImGuiCol_SeparatorHovered   ] = ImVec4(a.x, a.y, a.z, 0.70f);
    c[ImGuiCol_SeparatorActive    ] = ImVec4(a.x * 0.85f, a.y * 0.85f, a.z * 0.85f, 1.00f);
    c[ImGuiCol_NavHighlight       ] = ImVec4(a.x, a.y, a.z, 0.90f);
    c[ImGuiCol_DragDropTarget     ] = ImVec4(a.x, a.y, a.z, 0.90f);
    c[ImGuiCol_TextSelectedBg     ] = ImVec4(a.x, a.y, a.z, 0.35f);
}

// 应用随字体大小和界面密度缩放的动态几何尺寸。
// 每帧调用以保持内边距/间距与当前字体缩放成比例。
//   fontScale: 当前 FontScaleMain (如 1.3)
//   density:   0=紧凑 1=标准 2=宽松
inline void ApplyDynamicGeometry(float fontScale, int density) {
    ImGuiStyle& style = ImGui::GetStyle();
    const float s = fontScale;                          // 字体相对缩放
    const float d = (density == 0) ? 0.85f              // 紧凑
                  : (density == 2) ? 1.20f              // 宽松
                  : 1.00f;                              // 标准
    // 圆角 - 保持视觉稳定（仅轻微缩放以避免过小的尖锐边角）
    style.WindowRounding     = 8.0f;
    style.ChildRounding      = 6.0f;
    style.FrameRounding      = 5.0f;
    style.PopupRounding      = 6.0f;
    style.ScrollbarRounding  = 9.0f;
    style.GrabRounding       = 5.0f;
    style.TabRounding        = 6.0f;
    // 边框 - 固定 1px
    style.WindowBorderSize   = 1.0f;
    style.ChildBorderSize    = 1.0f;
    style.PopupBorderSize    = 1.0f;
    style.FrameBorderSize    = 0.0f;
    // 内边距和间距随字体和密度缩放，使按钮/框架随文字增长
    style.FramePadding       = ImVec2(12.0f * s * d, 6.0f * s * d);
    style.WindowPadding      = ImVec2(16.0f * s * d, 16.0f * s * d);
    style.ItemSpacing        = ImVec2(12.0f * s * d, 8.0f * s * d);
    style.ItemInnerSpacing   = ImVec2(8.0f * s * d, 6.0f * s * d);
    style.ScrollbarSize      = 16.0f * s;
    style.IndentSpacing      = 20.0f * s * d;
}

// 应用通用样式几何（圆角、内边距、间距）- 1.3x 字体时的基础值。
inline void ApplyThemeGeometry() {
    ImGuiStyle& style = ImGui::GetStyle();
    style.WindowRounding     = 8.0f;
    style.ChildRounding      = 6.0f;
    style.FrameRounding      = 5.0f;
    style.PopupRounding      = 6.0f;
    style.ScrollbarRounding  = 9.0f;
    style.GrabRounding       = 5.0f;
    style.TabRounding        = 6.0f;
    style.WindowBorderSize   = 1.0f;
    style.ChildBorderSize    = 1.0f;
    style.PopupBorderSize    = 1.0f;
    style.FrameBorderSize    = 0.0f;
    style.FramePadding       = ImVec2(12.0f, 6.0f);
    style.WindowPadding      = ImVec2(16.0f, 16.0f);
    style.ItemSpacing        = ImVec2(12.0f, 8.0f);
    style.ItemInnerSpacing   = ImVec2(8.0f, 6.0f);
    style.ScrollbarSize      = 16.0f;
}

// 柔和浅色主题 - 哑光暖灰色（不太亮）配舒适的对比度
inline void ApplyLightTheme() {
    ApplyThemeGeometry();
    ImGuiStyle& style = ImGui::GetStyle();
    ImVec4* c = style.Colors;

    // 背景 - 哑光浅灰（调暗以减轻视觉疲劳）
    c[ImGuiCol_WindowBg           ] = ImVec4(0.83f, 0.84f, 0.86f, 1.00f);
    c[ImGuiCol_ChildBg            ] = ImVec4(0.87f, 0.88f, 0.90f, 1.00f);
    c[ImGuiCol_PopupBg            ] = ImVec4(0.89f, 0.90f, 0.92f, 0.98f);
    c[ImGuiCol_Border             ] = ImVec4(0.58f, 0.60f, 0.64f, 0.70f);
    c[ImGuiCol_BorderShadow       ] = ImVec4(0.00f, 0.00f, 0.00f, 0.00f);
    // 文字 - 深炭色以保证可读性
    c[ImGuiCol_Text               ] = ImVec4(0.13f, 0.14f, 0.16f, 1.00f);
    c[ImGuiCol_TextDisabled       ] = ImVec4(0.45f, 0.46f, 0.49f, 1.00f);
    // 按钮 - 中等石板蓝，与背景明显区分
    c[ImGuiCol_Button             ] = ImVec4(0.50f, 0.59f, 0.69f, 1.00f);
    c[ImGuiCol_ButtonHovered      ] = ImVec4(0.42f, 0.52f, 0.64f, 1.00f);
    c[ImGuiCol_ButtonActive       ] = ImVec4(0.34f, 0.44f, 0.56f, 1.00f);
    // 框架 - 浅色但非纯白
    c[ImGuiCol_FrameBg            ] = ImVec4(0.93f, 0.94f, 0.95f, 1.00f);
    c[ImGuiCol_FrameBgHovered     ] = ImVec4(0.86f, 0.88f, 0.91f, 1.00f);
    c[ImGuiCol_FrameBgActive      ] = ImVec4(0.80f, 0.83f, 0.88f, 1.00f);
    // 标题栏 - 较深灰色以增加层次感
    c[ImGuiCol_TitleBg            ] = ImVec4(0.70f, 0.72f, 0.76f, 1.00f);
    c[ImGuiCol_TitleBgActive      ] = ImVec4(0.64f, 0.67f, 0.72f, 1.00f);
    c[ImGuiCol_TitleBgCollapsed   ] = ImVec4(0.76f, 0.77f, 0.80f, 1.00f);
    // 标签页 - 清晰的层次结构
    c[ImGuiCol_Tab                ] = ImVec4(0.74f, 0.76f, 0.79f, 1.00f);
    c[ImGuiCol_TabHovered         ] = ImVec4(0.54f, 0.62f, 0.72f, 1.00f);
    c[ImGuiCol_TabActive          ] = ImVec4(0.67f, 0.70f, 0.75f, 1.00f);
    c[ImGuiCol_TabUnfocused       ] = ImVec4(0.77f, 0.79f, 0.81f, 1.00f);
    c[ImGuiCol_TabUnfocusedActive ] = ImVec4(0.72f, 0.74f, 0.78f, 1.00f);
    // 滚动条 - 可见但不分散注意力
    c[ImGuiCol_ScrollbarBg        ] = ImVec4(0.00f, 0.00f, 0.00f, 0.00f);
    c[ImGuiCol_ScrollbarGrab      ] = ImVec4(0.55f, 0.58f, 0.63f, 0.60f);
    c[ImGuiCol_ScrollbarGrabHovered] = ImVec4(0.43f, 0.47f, 0.53f, 0.80f);
    c[ImGuiCol_ScrollbarGrabActive] = ImVec4(0.35f, 0.39f, 0.45f, 1.00f);
    // 强调色 - 石板蓝
    c[ImGuiCol_CheckMark          ] = ImVec4(0.35f, 0.48f, 0.62f, 1.00f);
    c[ImGuiCol_SliderGrab         ] = ImVec4(0.48f, 0.58f, 0.68f, 0.85f);
    c[ImGuiCol_SliderGrabActive   ] = ImVec4(0.38f, 0.48f, 0.60f, 1.00f);
    c[ImGuiCol_Header             ] = ImVec4(0.48f, 0.58f, 0.68f, 0.70f);
    c[ImGuiCol_HeaderHovered      ] = ImVec4(0.48f, 0.58f, 0.68f, 0.50f);
    c[ImGuiCol_HeaderActive       ] = ImVec4(0.38f, 0.48f, 0.60f, 0.90f);
    // 分隔线 - 可见
    c[ImGuiCol_Separator          ] = ImVec4(0.58f, 0.60f, 0.64f, 0.65f);
    c[ImGuiCol_SeparatorHovered   ] = ImVec4(0.48f, 0.58f, 0.68f, 0.70f);
    c[ImGuiCol_SeparatorActive    ] = ImVec4(0.38f, 0.48f, 0.60f, 1.00f);
    // 调整大小手柄
    c[ImGuiCol_ResizeGrip         ] = ImVec4(0.55f, 0.58f, 0.63f, 0.30f);
    c[ImGuiCol_ResizeGripHovered  ] = ImVec4(0.48f, 0.58f, 0.68f, 0.60f);
    c[ImGuiCol_ResizeGripActive   ] = ImVec4(0.38f, 0.48f, 0.60f, 0.90f);
    // 其他
    c[ImGuiCol_MenuBarBg          ] = ImVec4(0.76f, 0.77f, 0.80f, 1.00f);
    c[ImGuiCol_TextSelectedBg     ] = ImVec4(0.48f, 0.58f, 0.68f, 0.35f);
    c[ImGuiCol_DragDropTarget     ] = ImVec4(0.48f, 0.58f, 0.68f, 0.90f);
    c[ImGuiCol_NavHighlight       ] = ImVec4(0.48f, 0.58f, 0.68f, 0.90f);
    c[ImGuiCol_NavWindowingHighlight] = ImVec4(1.00f, 1.00f, 1.00f, 0.70f);
    c[ImGuiCol_NavWindowingDimBg  ] = ImVec4(0.70f, 0.70f, 0.70f, 0.20f);
    c[ImGuiCol_ModalWindowDimBg   ] = ImVec4(0.20f, 0.20f, 0.20f, 0.35f);
}

// 柔和深色主题 - 深石板色配良好的可读性
inline void ApplyDarkTheme() {
    ApplyThemeGeometry();
    ImGuiStyle& style = ImGui::GetStyle();
    ImVec4* c = style.Colors;

    // 背景 - 深石板色（非刺眼纯黑）
    c[ImGuiCol_WindowBg           ] = ImVec4(0.14f, 0.15f, 0.17f, 1.00f);
    c[ImGuiCol_ChildBg            ] = ImVec4(0.17f, 0.18f, 0.20f, 1.00f);
    c[ImGuiCol_PopupBg            ] = ImVec4(0.19f, 0.20f, 0.23f, 0.98f);
    c[ImGuiCol_Border             ] = ImVec4(0.38f, 0.40f, 0.44f, 0.65f);
    c[ImGuiCol_BorderShadow       ] = ImVec4(0.00f, 0.00f, 0.00f, 0.00f);
    // 文字 - 明亮以保证对比度（接近白色）
    c[ImGuiCol_Text               ] = ImVec4(0.92f, 0.93f, 0.95f, 1.00f);
    c[ImGuiCol_TextDisabled       ] = ImVec4(0.52f, 0.53f, 0.55f, 1.00f);
    // 按钮 - 中等石板蓝，比背景浅以增加可见性
    c[ImGuiCol_Button             ] = ImVec4(0.38f, 0.43f, 0.50f, 1.00f);
    c[ImGuiCol_ButtonHovered      ] = ImVec4(0.46f, 0.52f, 0.62f, 1.00f);
    c[ImGuiCol_ButtonActive       ] = ImVec4(0.54f, 0.61f, 0.72f, 1.00f);
    // 框架 - 比背景浅
    c[ImGuiCol_FrameBg            ] = ImVec4(0.22f, 0.24f, 0.28f, 1.00f);
    c[ImGuiCol_FrameBgHovered     ] = ImVec4(0.28f, 0.31f, 0.37f, 1.00f);
    c[ImGuiCol_FrameBgActive      ] = ImVec4(0.34f, 0.38f, 0.46f, 1.00f);
    // 标题栏
    c[ImGuiCol_TitleBg            ] = ImVec4(0.20f, 0.22f, 0.25f, 1.00f);
    c[ImGuiCol_TitleBgActive      ] = ImVec4(0.26f, 0.29f, 0.33f, 1.00f);
    c[ImGuiCol_TitleBgCollapsed   ] = ImVec4(0.17f, 0.18f, 0.20f, 1.00f);
    // 标签页
    c[ImGuiCol_Tab                ] = ImVec4(0.22f, 0.24f, 0.28f, 1.00f);
    c[ImGuiCol_TabHovered         ] = ImVec4(0.34f, 0.40f, 0.50f, 1.00f);
    c[ImGuiCol_TabActive          ] = ImVec4(0.28f, 0.32f, 0.39f, 1.00f);
    c[ImGuiCol_TabUnfocused       ] = ImVec4(0.20f, 0.22f, 0.25f, 1.00f);
    c[ImGuiCol_TabUnfocusedActive ] = ImVec4(0.25f, 0.27f, 0.31f, 1.00f);
    // 滚动条
    c[ImGuiCol_ScrollbarBg        ] = ImVec4(0.00f, 0.00f, 0.00f, 0.00f);
    c[ImGuiCol_ScrollbarGrab      ] = ImVec4(0.40f, 0.43f, 0.48f, 0.55f);
    c[ImGuiCol_ScrollbarGrabHovered] = ImVec4(0.52f, 0.56f, 0.63f, 0.80f);
    c[ImGuiCol_ScrollbarGrabActive] = ImVec4(0.60f, 0.65f, 0.72f, 1.00f);
    // 强调色
    c[ImGuiCol_CheckMark          ] = ImVec4(0.65f, 0.74f, 0.84f, 1.00f);
    c[ImGuiCol_SliderGrab         ] = ImVec4(0.48f, 0.55f, 0.65f, 0.85f);
    c[ImGuiCol_SliderGrabActive   ] = ImVec4(0.58f, 0.66f, 0.76f, 1.00f);
    c[ImGuiCol_Header             ] = ImVec4(0.38f, 0.44f, 0.52f, 0.75f);
    c[ImGuiCol_HeaderHovered      ] = ImVec4(0.44f, 0.50f, 0.60f, 0.55f);
    c[ImGuiCol_HeaderActive       ] = ImVec4(0.50f, 0.58f, 0.68f, 0.95f);
    // 分隔线 - 可见
    c[ImGuiCol_Separator          ] = ImVec4(0.38f, 0.40f, 0.44f, 0.60f);
    c[ImGuiCol_SeparatorHovered   ] = ImVec4(0.50f, 0.58f, 0.68f, 0.70f);
    c[ImGuiCol_SeparatorActive    ] = ImVec4(0.60f, 0.68f, 0.78f, 1.00f);
    // 调整大小手柄
    c[ImGuiCol_ResizeGrip         ] = ImVec4(0.40f, 0.43f, 0.48f, 0.25f);
    c[ImGuiCol_ResizeGripHovered  ] = ImVec4(0.50f, 0.58f, 0.68f, 0.60f);
    c[ImGuiCol_ResizeGripActive   ] = ImVec4(0.60f, 0.68f, 0.78f, 0.90f);
    // 其他
    c[ImGuiCol_MenuBarBg          ] = ImVec4(0.20f, 0.22f, 0.25f, 1.00f);
    c[ImGuiCol_TextSelectedBg     ] = ImVec4(0.50f, 0.58f, 0.68f, 0.40f);
    c[ImGuiCol_DragDropTarget     ] = ImVec4(0.58f, 0.66f, 0.76f, 0.90f);
    c[ImGuiCol_NavHighlight       ] = ImVec4(0.58f, 0.66f, 0.76f, 0.90f);
    c[ImGuiCol_NavWindowingHighlight] = ImVec4(1.00f, 1.00f, 1.00f, 0.60f);
    c[ImGuiCol_NavWindowingDimBg  ] = ImVec4(0.15f, 0.15f, 0.15f, 0.25f);
    c[ImGuiCol_ModalWindowDimBg   ] = ImVec4(0.08f, 0.08f, 0.08f, 0.40f);
}
