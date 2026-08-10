// ui_settings.h - 设置弹窗
//
// 从 ui_main_window.cpp 中抽取，以更好地分离关注点。
// 设置弹窗包含外观选项（主题、强调色、字体大小、界面密度、缩略图大小），
// 以居中模态弹窗形式显示。
#pragma once
#include "app_state.h"

// 绘制设置弹窗（模态）。每帧调用；内部检查
// state.ui.showSettings，仅在打开时渲染。
void DrawSettingsPopup(AppState& state);
