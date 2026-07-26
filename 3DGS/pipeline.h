#pragma once
#include "image_manager.h"
#include <vector>
#include <atomic>
#include <thread>
#include <string>

// Standard 3DGS Gaussian point (62 attributes as per PLY format)
struct GaussianPoint {
    // Position
    float x, y, z;
    // Normal (typically 0 in 3DGS)
    float nx, ny, nz;
    // SH DC coefficients (base color)
    float f_dc_0, f_dc_1, f_dc_2;
    // SH rest coefficients (45 values, higher-order SH)
    float f_rest[45];
    // Opacity
    float opacity;
    // Scale (3-axis)
    float scale_0, scale_1, scale_2;
    // Rotation quaternion
    float rot_0, rot_1, rot_2, rot_3;
};

struct RenderResult {
    std::vector<GaussianPoint> points;
    int  imageCount    = 0;
    int  sourceWidth   = 0;
    int  sourceHeight  = 0;
    bool completed     = false;
};

struct PipelineConfig {
    int   sampleStep       = 4;       // Pixel sampling step (1=every pixel, 4=every 4th pixel)
    float pointSpacing     = 1.0f;    // World-space spacing between points
    float sceneScale       = 2.0f;    // Overall scene scale
    float baseOpacity      = 0.85f;   // Base opacity for generated Gaussians
    float baseScale        = 0.3f;    // Base scale for generated Gaussians
    bool  verbose          = true;    // Log detailed progress
};

class Pipeline {
public:
    Pipeline();
    ~Pipeline();

    // Start the pipeline (runs in background thread)
    bool Start(const std::vector<ImageEntry>& images, const PipelineConfig& config = PipelineConfig());

    // Stop the pipeline
    void Stop();

    // Get current progress [0.0, 1.0]
    float GetProgress() const { return m_progress.load(); }

    // Get current status message (for UI display)
    std::string GetStatus() const { return m_status; }

    // Is the pipeline currently running?
    bool IsRunning() const { return m_running.load(); }

    // Has the pipeline finished?
    bool IsFinished() const { return m_finished.load(); }

    // Get the result (valid after IsFinished() returns true)
    const RenderResult& GetResult() const { return m_result; }

    // Reset state for a new run
    void Reset();

private:
    std::thread             m_thread;
    std::atomic<float>      m_progress{0.0f};
    std::atomic<bool>       m_running{false};
    std::atomic<bool>       m_finished{false};
    std::atomic<bool>       m_cancel{false};
    std::string             m_status;
    RenderResult            m_result;
    PipelineConfig          m_config;

    // Main processing function (runs in background thread)
    void Process(std::vector<ImageEntry> images);

    // Generate Gaussian points from a single image
    void ProcessImage(const ImageEntry& entry, int imageIndex, int totalImages,
                      std::vector<GaussianPoint>& outPoints);

    // Create a single Gaussian point from a pixel
    static GaussianPoint MakePoint(float x, float y, float z,
                                    unsigned char r, unsigned char g, unsigned char b,
                                    float scale, float opacity);
};
