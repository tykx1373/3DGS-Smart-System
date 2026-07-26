// 3DGS GUI - ImGui + GLFW + OpenGL3
// 3D Gaussian Splatting Tool

#include "imgui.h"
#include "imgui_impl_glfw.h"
#include "imgui_impl_opengl3.h"
#include <stdio.h>
#define GL_SILENCE_DEPRECATION
#include <GLFW/glfw3.h>

#include "app_state.h"
#include "log_system.h"
#include "theme.h"
#include "ui_main_window.h"

// [Win32] Link with legacy_stdio_definitions for VS2015+ compatibility with older pre-compiled GLFW
#if defined(_MSC_VER) && (_MSC_VER >= 1900)
#pragma comment(lib, "legacy_stdio_definitions")
#endif

// ==================== GLFW Error Callback ====================
static void glfw_error_callback(int error, const char* description) {
    fprintf(stderr, "GLFW Error %d: %s\n", error, description);
}

// ==================== Main ====================
int main(int, char**) {
    glfwSetErrorCallback(glfw_error_callback);
    if (!glfwInit())
        return 1;

    // GL 3.0 + GLSL 130
    const char* glsl_version = "#version 130";
    glfwWindowHint(GLFW_CONTEXT_VERSION_MAJOR, 3);
    glfwWindowHint(GLFW_CONTEXT_VERSION_MINOR, 0);

    // Create window
    GLFWwindow* window = glfwCreateWindow(1280, 720, u8"3DGS - 三维高斯泼溅工具", nullptr, nullptr);
    if (window == nullptr)
        return 1;
    glfwMakeContextCurrent(window);
    glfwSwapInterval(1); // Enable vsync

    // Setup Dear ImGui context
    IMGUI_CHECKVERSION();
    ImGui::CreateContext();
    ImGuiIO& io = ImGui::GetIO();
    io.ConfigFlags |= ImGuiConfigFlags_NavEnableKeyboard;

    // Load Chinese font (Microsoft YaHei) with full Chinese glyph ranges
    ImFont* font = io.Fonts->AddFontFromFileTTF(
        "C:\\Windows\\Fonts\\msyh.ttc",
        18.0f,                       // Base font size
        nullptr,                     // No oversampling
        io.Fonts->GetGlyphRangesChineseFull()
    );
    if (font == nullptr) {
        // Fallback to SimHei if YaHei not found
        font = io.Fonts->AddFontFromFileTTF(
            "C:\\Windows\\Fonts\\simhei.ttf",
            18.0f,
            nullptr,
            io.Fonts->GetGlyphRangesChineseFull()
        );
    }
    IM_ASSERT(font != nullptr && "Failed to load any Chinese font!");
    // NOTE: Do NOT call io.Fonts->Build() here - the OpenGL3 backend handles it
    // after ImGui_ImplOpenGL3_Init() in newer ImGui versions (1.92+)

    // Setup Dear ImGui style - apply soft light theme by default
    ApplyLightTheme();
    ImGui::GetStyle().FontScaleMain = 1.3f;

    // Setup Platform/Renderer backends
    ImGui_ImplGlfw_InitForOpenGL(window, true);
    ImGui_ImplOpenGL3_Init(glsl_version);

    // Initialize log system (creates logs/ directory and opens log file)
    LogSystem::Init();

    // Initialize application
    AppState appState;
    LogSystem::Info(u8"3DGS 工具已初始化");
    LogSystem::Info(u8"就绪，等待导入图片");

    // Main loop
    while (!glfwWindowShouldClose(window)) {
        glfwPollEvents();
        if (glfwGetWindowAttrib(window, GLFW_ICONIFIED) != 0) {
            ImGui_ImplGlfw_Sleep(10);
            continue;
        }

        // Start the Dear ImGui frame
        ImGui_ImplOpenGL3_NewFrame();
        ImGui_ImplGlfw_NewFrame();
        ImGui::NewFrame();

        // Draw main window with tabs
        DrawMainWindow(appState);

        // Rendering
        ImGui::Render();
        int display_w, display_h;
        glfwGetFramebufferSize(window, &display_w, &display_h);
        glViewport(0, 0, display_w, display_h);
        ImVec4 clear_color = ImVec4(0.20f, 0.20f, 0.20f, 1.00f);
        glClearColor(clear_color.x * clear_color.w, clear_color.y * clear_color.w, clear_color.z * clear_color.w, clear_color.w);
        glClear(GL_COLOR_BUFFER_BIT);
        ImGui_ImplOpenGL3_RenderDrawData(ImGui::GetDrawData());

        glfwSwapBuffers(window);
    }

    // Cleanup: stop pipeline first to join background thread
    appState.pipeline.Stop();
    appState.imageManager.ReleaseTextures();
    ImGui_ImplOpenGL3_Shutdown();
    ImGui_ImplGlfw_Shutdown();
    ImGui::DestroyContext();

    glfwDestroyWindow(window);
    glfwTerminate();

    return 0;
}
