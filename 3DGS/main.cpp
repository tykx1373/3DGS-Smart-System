// main.cpp - 应用程序入口
//
// 初始化 GLFW + OpenGL 3.0 + Dear ImGui，加载字体，并运行
// 主渲染循环。应用程序状态 (AppState) 在此创建，
// 并通过 DrawMainWindow() 传递给 UI 层。
//
// 字体渲染:
//   - 基础栅格化 22px，3xH/2xV 超采样以保证文字清晰
//   - 启用 PixelSnapH 进行像素网格对齐
//   - FontScaleMain 在运行时通过 Ctrl+滚轮调整 (在 ui_main_window 中)
//   - 不要手动调用 io.Fonts->Build()；在 ImGui 1.92+ 中
//     由 OpenGL3 后端在 ImGui_ImplOpenGL3_Init() 之后处理
//
// 清理顺序（重要）:
//   1. 先停止管线线程 (join) 再销毁 OpenGL 上下文
//   2. 释放图片纹理
//   3. 关闭 ImGui 后端
//   4. 销毁 GLFW 窗口
//
#include "imgui.h"
#include "imgui_impl_glfw.h"
#include "imgui_impl_opengl3.h"
#include <stdio.h>
#define GL_SILENCE_DEPRECATION
#include <GLFW/glfw3.h>
#define GLFW_EXPOSE_NATIVE_WIN32
#include <GLFW/glfw3native.h>

#include "app_state.h"
#include "log_system.h"
#include "theme.h"
#include "ui_main_window.h"
#include "file_dialog.h"
#include "project_io.h"

// [Win32] 链接 legacy_stdio_definitions 以兼容 VS2015+ 与旧版预编译 GLFW
#if defined(_MSC_VER) && (_MSC_VER >= 1900)
#pragma comment(lib, "legacy_stdio_definitions")
#endif

// ==================== GLFW 错误回调 ====================
static void glfw_error_callback(int error, const char* description) {
    // Windows 子系统没有控制台，将错误写入日志系统
    char buf[256];
    snprintf(buf, sizeof(buf), u8"GLFW 错误 %d: %s", error, description);
    LogSystem::Error(buf);
}

// ==================== 未捕获异常处理 ====================
// 捕获未处理的 C++ 异常和结构化异常，写入日志后正常退出
static LONG WINAPI unhandled_exception_handler(EXCEPTION_POINTERS* ep) {
    LogSystem::Error(u8"程序发生未捕获异常 (代码: " +
        std::to_string((unsigned long)ep->ExceptionRecord->ExceptionCode) + ")");
    return EXCEPTION_EXECUTE_HANDLER;
}

// ==================== 主函数 ====================
int main(int, char**) {
    // 注册未捕获异常处理器（在日志系统初始化前，记录到全局缓冲）
    SetUnhandledExceptionFilter(unhandled_exception_handler);

    glfwSetErrorCallback(glfw_error_callback);
    if (!glfwInit())
        return 1;

    // GL 3.0 + GLSL 130
    const char* glsl_version = "#version 130";
    glfwWindowHint(GLFW_CONTEXT_VERSION_MAJOR, 3);
    glfwWindowHint(GLFW_CONTEXT_VERSION_MINOR, 0);

    // 创建窗口
    GLFWwindow* window = glfwCreateWindow(1280, 720, u8"3DGS - 三维高斯泼溅工具", nullptr, nullptr);
    if (window == nullptr)
        return 1;
    glfwMakeContextCurrent(window);
    glfwSwapInterval(1); // 启用垂直同步

    // 设置 Dear ImGui 上下文
    IMGUI_CHECKVERSION();
    ImGui::CreateContext();
    ImGuiIO& io = ImGui::GetIO();
    io.ConfigFlags |= ImGuiConfigFlags_NavEnableKeyboard;

    // 加载中文字体 (微软雅黑)，超采样以保证清晰度。
    // 22px 基础尺寸避免 FontScaleMain > 1.0 时的模糊（无纹理拉伸）。
    ImFontConfig fontCfg;
    fontCfg.OversampleH = 3;           // 水平超采样，使边缘锐利
    fontCfg.OversampleV = 2;           // 垂直超采样，使边缘锐利
    fontCfg.PixelSnapH  = true;        // 字形对齐到像素网格
    fontCfg.MergeMode   = false;

    ImFont* font = io.Fonts->AddFontFromFileTTF(
        "C:\\Windows\\Fonts\\msyh.ttc",
        22.0f,
        &fontCfg,
        io.Fonts->GetGlyphRangesChineseFull()
    );
    if (font == nullptr) {
        // 未找到雅黑则回退到黑体
        font = io.Fonts->AddFontFromFileTTF(
            "C:\\Windows\\Fonts\\simhei.ttf",
            22.0f,
            &fontCfg,
            io.Fonts->GetGlyphRangesChineseFull()
        );
    }
    IM_ASSERT(font != nullptr && "Failed to load any Chinese font!");

    // 设置 Dear ImGui 样式 - 默认应用柔和浅色主题。
    // FontScaleMain 设为默认 1.3x（在 UiState::fontScale 中设置）。
    ApplyLightTheme();
    ImGui::GetStyle().FontScaleMain = 1.0f;  // 无纹理缩放；字体以 22px 栅格化

    // 设置平台/渲染器后端
    ImGui_ImplGlfw_InitForOpenGL(window, true);
    ImGui_ImplOpenGL3_Init(glsl_version);

    // 初始化日志系统（创建 logs/ 目录并打开日志文件）
    LogSystem::Init();

    // 设置文件对话框的父窗口句柄，使文件对话框成为模态对话框。
    // 设置 hwndOwner 后，操作系统会禁用父窗口的输入，对话框始终置前，
    // 用户无法在对话框关闭前操作主窗口。
    FileDialog::SetOwnerWindow((NativeWindowHandle)glfwGetWin32Window(window));

    // 初始化应用程序状态
    AppState appState;

    // 检测显卡并自动应用推荐参数
    appState.gpuInfo = DetectGpu();
    if (appState.gpuInfo.detected) {
        LogSystem::Info(u8"检测到显卡: " + appState.gpuInfo.name);
        LogSystem::Info(std::string(u8"分类: ") + GetGpuTypeName(appState.gpuInfo.type) +
                        u8", 显存: " + std::to_string(appState.gpuInfo.vramMB) + u8" MB");

        // 自动应用推荐参数
        appState.sampleStep = appState.gpuInfo.recSampleStep;
        appState.sceneScale = appState.gpuInfo.recSceneScale;
        appState.baseScale  = appState.gpuInfo.recBaseScale;
        appState.ui.gpuType = appState.gpuInfo.type;
        appState.gpuAppliedRecommend = true;
        LogSystem::Info(u8"已自动应用推荐渲染参数");
    } else {
        LogSystem::Warn(u8"未能检测到显卡信息，使用默认参数");
    }

    LogSystem::Info(u8"3DGS 工具已初始化");
    LogSystem::Info(u8"就绪，等待导入图片");

    // 主循环
    while (!glfwWindowShouldClose(window)) {
        glfwPollEvents();
        if (glfwGetWindowAttrib(window, GLFW_ICONIFIED) != 0) {
            ImGui_ImplGlfw_Sleep(10);
            continue;
        }

        // 开始 Dear ImGui 帧
        ImGui_ImplOpenGL3_NewFrame();
        ImGui_ImplGlfw_NewFrame();
        ImGui::NewFrame();

        // 绘制带标签页的主窗口
        DrawMainWindow(appState);

        // 渲染
        ImGui::Render();
        int display_w, display_h;
        glfwGetFramebufferSize(window, &display_w, &display_h);
        glViewport(0, 0, display_w, display_h);
        ImVec4 clear_color = ImVec4(0.20f, 0.20f, 0.20f, 1.00f);
        glClearColor(clear_color.x * clear_color.w, clear_color.y * clear_color.w, clear_color.z * clear_color.w, clear_color.w);
        glClear(GL_COLOR_BUFFER_BIT);
        ImGui_ImplOpenGL3_RenderDrawData(ImGui::GetDrawData());

        glfwSwapBuffers(window);

        // ================================================================
        // 帧外处理文件对话框
        //
        // Win32 文件对话框 (GetOpenFileNameW / GetSaveFileNameW) 是同步阻塞
        // 调用。如果在 ImGui 帧内执行，对话框关闭后 GLFW 积压的鼠标事件会被
        // ImGui 当作按钮再次点击，导致对话框反复弹出。
        //
        // 解决方案：按钮点击时仅设置 pendingAction 标志（在 ui_control_panel.cpp），
        // 在 ImGui 渲染完成、交换缓冲后（此处）执行文件对话框，
        // 返回后清空 GLFW 和 ImGui 的残留输入事件。
        // ================================================================
        if (appState.ui.pendingAction != PendingAction::None) {
            // 先保存 pendingAction，因为文件对话框可能耗时较长
            PendingAction action = appState.ui.pendingAction;

            try {
                switch (action) {
                    case PendingAction::ImportImages: {
                        auto files = FileDialog::OpenFiles();
                        // 文件对话框返回后，确保 OpenGL 上下文是当前的。
                        // 模态对话框运行自己的消息循环，某些驱动可能导致上下文丢失。
                        glfwMakeContextCurrent(window);
                        if (!files.empty()) {
                            appState.imageManager.AddImages(files);
                            appState.projectConfig.modifiedTime = ProjectIO::GetCurrentTimeISO8601();
                            appState.renderDone = false;
                        } else {
                            LogSystem::Info(u8"未选择图片");
                        }
                        break;
                    }
                    case PendingAction::LoadProject: {
                        std::string path = FileDialog::OpenProjectFile();
                        glfwMakeContextCurrent(window);
                        if (!path.empty()) {
                            ProjectIO::LoadProject(path, appState.projectConfig, appState.imageManager);
                            appState.renderDone = false;
                        } else {
                            LogSystem::Info(u8"已取消加载项目");
                        }
                        break;
                    }
                    case PendingAction::SaveProject: {
                        std::string savePath = FileDialog::SaveFile();
                        glfwMakeContextCurrent(window);
                        if (!savePath.empty()) {
                            appState.projectConfig.outputPath = savePath;
                            appState.projectConfig.modifiedTime = ProjectIO::GetCurrentTimeISO8601();
                            ProjectIO::SaveProject(savePath, appState.projectConfig, appState.imageManager.GetImages());
                        } else {
                            LogSystem::Info(u8"已取消保存");
                        }
                        break;
                    }
                    case PendingAction::ExportPly: {
                        std::string savePath = FileDialog::SavePlyFile();
                        glfwMakeContextCurrent(window);
                        if (!savePath.empty()) {
                            appState.projectConfig.plyOutputPath = savePath;
                            ProjectIO::SavePly(savePath, appState.pipeline.GetResult());
                        } else {
                            LogSystem::Info(u8"已取消保存 PLY");
                        }
                        break;
                    }
                    default:
                        break;
                }
            } catch (const std::exception& e) {
                LogSystem::Error(std::string(u8"操作异常: ") + e.what());
            } catch (...) {
                LogSystem::Error(u8"操作发生未知异常");
            }

            // 清除待处理操作和活动弹窗标志
            appState.ui.pendingAction = PendingAction::None;
            appState.ui.activePopup = 0;
            appState.ui.popupNotice[0] = 0; // 清除任何残留提示

            // 设置输入守卫：忽略接下来 5 帧的用户输入，防止
            // 文件对话框关闭后 GLFW 残留的鼠标事件被 ImGui 当作按钮点击。
            appState.ui.inputGuard = 5;

            // 文件对话框返回后，处理残留事件。
            // 由于对话框是系统级模态（设置了 hwndOwner），对话框打开期间
            // 主窗口输入已被操作系统禁用，不会有残留的鼠标点击事件。
            // 此处仅调用 glfwPollEvents() 消化对话框关闭产生的窗口事件，
            // 确保 GLFW 内部状态一致。
            glfwPollEvents();
        }
    }

    // 清理：先停止管线以 join 后台线程，再销毁 GL 上下文
    appState.pipeline.Stop();
    appState.imageManager.ReleaseTextures();
    ImGui_ImplOpenGL3_Shutdown();
    ImGui_ImplGlfw_Shutdown();
    ImGui::DestroyContext();

    glfwDestroyWindow(window);
    glfwTerminate();

    return 0;
}
