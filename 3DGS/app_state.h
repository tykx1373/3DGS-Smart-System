#pragma once
#include "image_manager.h"
#include "project_io.h"
#include "pipeline.h"

struct AppState {
    ImageManager  imageManager;
    ProjectConfig projectConfig;
    Pipeline      pipeline;

    bool          isRendering   = false;
    bool          renderDone    = false;
    float         fontScale     = 1.3f;
    bool          isDarkTheme   = false;
    int           currentTab    = 0;  // 0=控制面板, 1=日志, 2=帮助

    // Pipeline settings
    int           sampleStep    = 4;    // Pixel sampling step
    float         sceneScale    = 2.0f;
    float         baseOpacity   = 0.85f;
    float         baseScale     = 0.3f;

    AppState() {
        projectConfig.createdTime  = ProjectIO::GetCurrentTimeISO8601();
        projectConfig.modifiedTime = projectConfig.createdTime;
    }

    // Convenience: is the background pipeline still running?
    bool IsPipelineRunning() const { return pipeline.IsRunning(); }
    float GetProgress() const { return pipeline.GetProgress(); }
};
