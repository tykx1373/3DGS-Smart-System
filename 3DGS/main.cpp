// 3DGS GUI - ImGui + GLFW + OpenGL3
// 3D Gaussian Splatting Tool Shell

#include "imgui.h"
#include "imgui_impl_glfw.h"
#include "imgui_impl_opengl3.h"
#include <stdio.h>
#define GL_SILENCE_DEPRECATION
#include <GLFW/glfw3.h>
#include <vector>
#include <string>

// [Win32] Link with legacy_stdio_definitions for VS2015+ compatibility with older pre-compiled GLFW
#if defined(_MSC_VER) && (_MSC_VER >= 1900)
#pragma comment(lib, "legacy_stdio_definitions")
#endif

// ==================== Global State ====================
struct AppState {
    std::vector<std::string> logMessages;
    std::string inputImagePath = "";
    bool isRendering = false;
    float renderProgress = 0.0f;
    std::string outputPath = "";
    float fontScale = 1.0f;
};

static AppState g_AppState;

// ==================== Utility ====================
void AddLog(const std::string& message) {
    g_AppState.logMessages.push_back(message);
}

// ==================== Button Callbacks (Shell) ====================
void OnImportImages() {
    AddLog("[Import Images] Button clicked - not implemented yet");
}

void OnRender() {
    AddLog("[Render] Button clicked - not implemented yet");
    g_AppState.isRendering = !g_AppState.isRendering;
    if (g_AppState.isRendering) {
        AddLog("Rendering started... (simulated)");
    } else {
        AddLog("Rendering stopped. (simulated)");
    }
}

void OnOutputResult() {
    AddLog("[Output Result] Button clicked - not implemented yet");
}

// ==================== GUI Drawing ====================
void DrawMainWindow() {
    // Full-size window covering the viewport
    ImGuiViewport* viewport = ImGui::GetMainViewport();
    ImGui::SetNextWindowPos(viewport->Pos);
    ImGui::SetNextWindowSize(viewport->Size);
    ImGuiWindowFlags window_flags = ImGuiWindowFlags_NoTitleBar | ImGuiWindowFlags_NoCollapse
        | ImGuiWindowFlags_NoResize | ImGuiWindowFlags_NoMove
        | ImGuiWindowFlags_NoBringToFrontOnFocus | ImGuiWindowFlags_NoNavFocus;
    ImGui::Begin("3DGS##MainWindow", nullptr, window_flags);

    // Ctrl+MouseWheel to zoom font
    ImGuiIO& io = ImGui::GetIO();
    if (io.KeyCtrl && io.MouseWheel != 0.0f) {
        g_AppState.fontScale += io.MouseWheel * 0.05f;
        g_AppState.fontScale = (g_AppState.fontScale < 0.5f) ? 0.5f : ((g_AppState.fontScale > 3.0f) ? 3.0f : g_AppState.fontScale);
        io.FontGlobalScale = g_AppState.fontScale;
    }

    // Tab bar
    if (ImGui::BeginTabBar("##MainTabs", ImGuiTabBarFlags_None)) {

        // ---- Tab 1: Control Panel ----
        if (ImGui::BeginTabItem("Control Panel")) {
            ImGui::Spacing();
            ImGui::Text("3D Gaussian Splatting Tool");
            ImGui::Separator();
            ImGui::Spacing();

            // Import Images
            if (ImGui::Button("Import Images", ImVec2(-1, 40))) {
                OnImportImages();
            }
            ImGui::Text("Current images: %s", g_AppState.inputImagePath.empty() ? "None" : g_AppState.inputImagePath.c_str());
            ImGui::Spacing();

            // Render
            if (ImGui::Button(g_AppState.isRendering ? "Stop Render" : "Start Render", ImVec2(-1, 40))) {
                OnRender();
            }
            if (g_AppState.isRendering) {
                ImGui::ProgressBar(g_AppState.renderProgress, ImVec2(-1, 0), "Render Progress");
            }
            ImGui::Spacing();

            // Output Result
            if (ImGui::Button("Output Result", ImVec2(-1, 40))) {
                OnOutputResult();
            }
            ImGui::Text("Output path: %s", g_AppState.outputPath.empty() ? "Not set" : g_AppState.outputPath.c_str());

            ImGui::EndTabItem();
        }

        // ---- Tab 2: Log ----
        if (ImGui::BeginTabItem("Log")) {
            ImGui::Spacing();
            if (ImGui::Button("Clear Log")) {
                g_AppState.logMessages.clear();
            }
            ImGui::Separator();

            ImGui::BeginChild("LogScroll", ImVec2(0, 0), ImGuiChildFlags_Borders);
            for (const auto& msg : g_AppState.logMessages) {
                ImGui::TextUnformatted(msg.c_str());
            }
            if (ImGui::GetScrollY() >= ImGui::GetScrollMaxY())
                ImGui::SetScrollHereY(1.0f);
            ImGui::EndChild();

            ImGui::EndTabItem();
        }

        ImGui::EndTabBar();
    }

    ImGui::End();
}

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
    GLFWwindow* window = glfwCreateWindow(1280, 720, "3DGS - 3D Gaussian Splatting Tool", nullptr, nullptr);
    if (window == nullptr)
        return 1;
    glfwMakeContextCurrent(window);
    glfwSwapInterval(1); // Enable vsync

    // Setup Dear ImGui context
    IMGUI_CHECKVERSION();
    ImGui::CreateContext();
    ImGuiIO& io = ImGui::GetIO();
    io.ConfigFlags |= ImGuiConfigFlags_NavEnableKeyboard; // Enable Keyboard Controls

    // Setup Dear ImGui style (Classic)
    ImGui::StyleColorsClassic();

    // Setup Platform/Renderer backends
    ImGui_ImplGlfw_InitForOpenGL(window, true);
    ImGui_ImplOpenGL3_Init(glsl_version);

    // Initial log messages
    AddLog("Welcome to 3DGS Tool");
    AddLog("System initialized");
    AddLog("Note: This is a UI shell, button functions are not yet implemented");

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
        DrawMainWindow();

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

    // Cleanup
    ImGui_ImplOpenGL3_Shutdown();
    ImGui_ImplGlfw_Shutdown();
    ImGui::DestroyContext();

    glfwDestroyWindow(window);
    glfwTerminate();

    return 0;
}
