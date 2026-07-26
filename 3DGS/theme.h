#pragma once
#include <imgui.h>

// Apply common style geometry (rounding, padding, spacing)
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

// Soft light theme - warm off-white with comfortable contrast
inline void ApplyLightTheme() {
    ApplyThemeGeometry();
    ImGuiStyle& style = ImGui::GetStyle();
    ImVec4* c = style.Colors;

    // Backgrounds - warm off-white
    c[ImGuiCol_WindowBg           ] = ImVec4(0.92f, 0.92f, 0.93f, 1.00f);
    c[ImGuiCol_ChildBg            ] = ImVec4(0.95f, 0.95f, 0.96f, 1.00f);
    c[ImGuiCol_PopupBg            ] = ImVec4(0.97f, 0.97f, 0.98f, 0.98f);
    c[ImGuiCol_Border             ] = ImVec4(0.65f, 0.67f, 0.70f, 0.70f);
    c[ImGuiCol_BorderShadow       ] = ImVec4(0.00f, 0.00f, 0.00f, 0.00f);
    // Text - strong dark charcoal for readability
    c[ImGuiCol_Text               ] = ImVec4(0.13f, 0.14f, 0.16f, 1.00f);
    c[ImGuiCol_TextDisabled       ] = ImVec4(0.48f, 0.49f, 0.52f, 1.00f);
    // Buttons - medium slate-blue, clearly distinct from bg
    c[ImGuiCol_Button             ] = ImVec4(0.53f, 0.62f, 0.72f, 1.00f);
    c[ImGuiCol_ButtonHovered      ] = ImVec4(0.44f, 0.54f, 0.66f, 1.00f);
    c[ImGuiCol_ButtonActive       ] = ImVec4(0.36f, 0.46f, 0.58f, 1.00f);
    // Frames - white, distinct from gray bg
    c[ImGuiCol_FrameBg            ] = ImVec4(1.00f, 1.00f, 1.00f, 1.00f);
    c[ImGuiCol_FrameBgHovered     ] = ImVec4(0.90f, 0.92f, 0.95f, 1.00f);
    c[ImGuiCol_FrameBgActive      ] = ImVec4(0.84f, 0.87f, 0.92f, 1.00f);
    // Title bars - darker gray for definition
    c[ImGuiCol_TitleBg            ] = ImVec4(0.78f, 0.80f, 0.84f, 1.00f);
    c[ImGuiCol_TitleBgActive      ] = ImVec4(0.72f, 0.75f, 0.80f, 1.00f);
    c[ImGuiCol_TitleBgCollapsed   ] = ImVec4(0.84f, 0.85f, 0.88f, 1.00f);
    // Tabs - clear hierarchy
    c[ImGuiCol_Tab                ] = ImVec4(0.82f, 0.84f, 0.87f, 1.00f);
    c[ImGuiCol_TabHovered         ] = ImVec4(0.62f, 0.70f, 0.80f, 1.00f);
    c[ImGuiCol_TabActive          ] = ImVec4(0.75f, 0.78f, 0.83f, 1.00f);
    c[ImGuiCol_TabUnfocused       ] = ImVec4(0.85f, 0.87f, 0.89f, 1.00f);
    c[ImGuiCol_TabUnfocusedActive ] = ImVec4(0.80f, 0.82f, 0.86f, 1.00f);
    // Scrollbars - visible but not distracting
    c[ImGuiCol_ScrollbarBg        ] = ImVec4(0.00f, 0.00f, 0.00f, 0.00f);
    c[ImGuiCol_ScrollbarGrab      ] = ImVec4(0.62f, 0.65f, 0.70f, 0.60f);
    c[ImGuiCol_ScrollbarGrabHovered] = ImVec4(0.50f, 0.54f, 0.60f, 0.80f);
    c[ImGuiCol_ScrollbarGrabActive] = ImVec4(0.42f, 0.46f, 0.52f, 1.00f);
    // Accents - slate-blue
    c[ImGuiCol_CheckMark          ] = ImVec4(0.35f, 0.48f, 0.62f, 1.00f);
    c[ImGuiCol_SliderGrab         ] = ImVec4(0.48f, 0.58f, 0.68f, 0.85f);
    c[ImGuiCol_SliderGrabActive   ] = ImVec4(0.38f, 0.48f, 0.60f, 1.00f);
    c[ImGuiCol_Header             ] = ImVec4(0.48f, 0.58f, 0.68f, 0.70f);
    c[ImGuiCol_HeaderHovered      ] = ImVec4(0.48f, 0.58f, 0.68f, 0.50f);
    c[ImGuiCol_HeaderActive       ] = ImVec4(0.38f, 0.48f, 0.60f, 0.90f);
    // Separator - visible
    c[ImGuiCol_Separator          ] = ImVec4(0.65f, 0.67f, 0.70f, 0.65f);
    c[ImGuiCol_SeparatorHovered   ] = ImVec4(0.48f, 0.58f, 0.68f, 0.70f);
    c[ImGuiCol_SeparatorActive    ] = ImVec4(0.38f, 0.48f, 0.60f, 1.00f);
    // Resize grip
    c[ImGuiCol_ResizeGrip         ] = ImVec4(0.62f, 0.65f, 0.70f, 0.30f);
    c[ImGuiCol_ResizeGripHovered  ] = ImVec4(0.48f, 0.58f, 0.68f, 0.60f);
    c[ImGuiCol_ResizeGripActive   ] = ImVec4(0.38f, 0.48f, 0.60f, 0.90f);
    // Misc
    c[ImGuiCol_MenuBarBg          ] = ImVec4(0.84f, 0.85f, 0.88f, 1.00f);
    c[ImGuiCol_TextSelectedBg     ] = ImVec4(0.48f, 0.58f, 0.68f, 0.35f);
    c[ImGuiCol_DragDropTarget     ] = ImVec4(0.48f, 0.58f, 0.68f, 0.90f);
    c[ImGuiCol_NavHighlight       ] = ImVec4(0.48f, 0.58f, 0.68f, 0.90f);
    c[ImGuiCol_NavWindowingHighlight] = ImVec4(1.00f, 1.00f, 1.00f, 0.70f);
    c[ImGuiCol_NavWindowingDimBg  ] = ImVec4(0.70f, 0.70f, 0.70f, 0.20f);
    c[ImGuiCol_ModalWindowDimBg   ] = ImVec4(0.20f, 0.20f, 0.20f, 0.35f);
}

// Soft dark theme - dark slate with good readability
inline void ApplyDarkTheme() {
    ApplyThemeGeometry();
    ImGuiStyle& style = ImGui::GetStyle();
    ImVec4* c = style.Colors;

    // Backgrounds - dark slate (not harsh black)
    c[ImGuiCol_WindowBg           ] = ImVec4(0.14f, 0.15f, 0.17f, 1.00f);
    c[ImGuiCol_ChildBg            ] = ImVec4(0.17f, 0.18f, 0.20f, 1.00f);
    c[ImGuiCol_PopupBg            ] = ImVec4(0.19f, 0.20f, 0.23f, 0.98f);
    c[ImGuiCol_Border             ] = ImVec4(0.38f, 0.40f, 0.44f, 0.65f);
    c[ImGuiCol_BorderShadow       ] = ImVec4(0.00f, 0.00f, 0.00f, 0.00f);
    // Text - bright for contrast (near white)
    c[ImGuiCol_Text               ] = ImVec4(0.92f, 0.93f, 0.95f, 1.00f);
    c[ImGuiCol_TextDisabled       ] = ImVec4(0.52f, 0.53f, 0.55f, 1.00f);
    // Buttons - medium slate-blue, lighter than bg for visibility
    c[ImGuiCol_Button             ] = ImVec4(0.38f, 0.43f, 0.50f, 1.00f);
    c[ImGuiCol_ButtonHovered      ] = ImVec4(0.46f, 0.52f, 0.62f, 1.00f);
    c[ImGuiCol_ButtonActive       ] = ImVec4(0.54f, 0.61f, 0.72f, 1.00f);
    // Frames - lighter than bg
    c[ImGuiCol_FrameBg            ] = ImVec4(0.22f, 0.24f, 0.28f, 1.00f);
    c[ImGuiCol_FrameBgHovered     ] = ImVec4(0.28f, 0.31f, 0.37f, 1.00f);
    c[ImGuiCol_FrameBgActive      ] = ImVec4(0.34f, 0.38f, 0.46f, 1.00f);
    // Title bars
    c[ImGuiCol_TitleBg            ] = ImVec4(0.20f, 0.22f, 0.25f, 1.00f);
    c[ImGuiCol_TitleBgActive      ] = ImVec4(0.26f, 0.29f, 0.33f, 1.00f);
    c[ImGuiCol_TitleBgCollapsed   ] = ImVec4(0.17f, 0.18f, 0.20f, 1.00f);
    // Tabs
    c[ImGuiCol_Tab                ] = ImVec4(0.22f, 0.24f, 0.28f, 1.00f);
    c[ImGuiCol_TabHovered         ] = ImVec4(0.34f, 0.40f, 0.50f, 1.00f);
    c[ImGuiCol_TabActive          ] = ImVec4(0.28f, 0.32f, 0.39f, 1.00f);
    c[ImGuiCol_TabUnfocused       ] = ImVec4(0.20f, 0.22f, 0.25f, 1.00f);
    c[ImGuiCol_TabUnfocusedActive ] = ImVec4(0.25f, 0.27f, 0.31f, 1.00f);
    // Scrollbars
    c[ImGuiCol_ScrollbarBg        ] = ImVec4(0.00f, 0.00f, 0.00f, 0.00f);
    c[ImGuiCol_ScrollbarGrab      ] = ImVec4(0.40f, 0.43f, 0.48f, 0.55f);
    c[ImGuiCol_ScrollbarGrabHovered] = ImVec4(0.52f, 0.56f, 0.63f, 0.80f);
    c[ImGuiCol_ScrollbarGrabActive] = ImVec4(0.60f, 0.65f, 0.72f, 1.00f);
    // Accents
    c[ImGuiCol_CheckMark          ] = ImVec4(0.65f, 0.74f, 0.84f, 1.00f);
    c[ImGuiCol_SliderGrab         ] = ImVec4(0.48f, 0.55f, 0.65f, 0.85f);
    c[ImGuiCol_SliderGrabActive   ] = ImVec4(0.58f, 0.66f, 0.76f, 1.00f);
    c[ImGuiCol_Header             ] = ImVec4(0.38f, 0.44f, 0.52f, 0.75f);
    c[ImGuiCol_HeaderHovered      ] = ImVec4(0.44f, 0.50f, 0.60f, 0.55f);
    c[ImGuiCol_HeaderActive       ] = ImVec4(0.50f, 0.58f, 0.68f, 0.95f);
    // Separator - visible
    c[ImGuiCol_Separator          ] = ImVec4(0.38f, 0.40f, 0.44f, 0.60f);
    c[ImGuiCol_SeparatorHovered   ] = ImVec4(0.50f, 0.58f, 0.68f, 0.70f);
    c[ImGuiCol_SeparatorActive    ] = ImVec4(0.60f, 0.68f, 0.78f, 1.00f);
    // Resize grip
    c[ImGuiCol_ResizeGrip         ] = ImVec4(0.40f, 0.43f, 0.48f, 0.25f);
    c[ImGuiCol_ResizeGripHovered  ] = ImVec4(0.50f, 0.58f, 0.68f, 0.60f);
    c[ImGuiCol_ResizeGripActive   ] = ImVec4(0.60f, 0.68f, 0.78f, 0.90f);
    // Misc
    c[ImGuiCol_MenuBarBg          ] = ImVec4(0.20f, 0.22f, 0.25f, 1.00f);
    c[ImGuiCol_TextSelectedBg     ] = ImVec4(0.50f, 0.58f, 0.68f, 0.40f);
    c[ImGuiCol_DragDropTarget     ] = ImVec4(0.58f, 0.66f, 0.76f, 0.90f);
    c[ImGuiCol_NavHighlight       ] = ImVec4(0.58f, 0.66f, 0.76f, 0.90f);
    c[ImGuiCol_NavWindowingHighlight] = ImVec4(1.00f, 1.00f, 1.00f, 0.60f);
    c[ImGuiCol_NavWindowingDimBg  ] = ImVec4(0.15f, 0.15f, 0.15f, 0.25f);
    c[ImGuiCol_ModalWindowDimBg   ] = ImVec4(0.08f, 0.08f, 0.08f, 0.40f);
}
