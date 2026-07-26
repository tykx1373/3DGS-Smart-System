#define STB_IMAGE_IMPLEMENTATION
#include "stb_image.h"

// Include Windows headers BEFORE OpenGL to avoid APIENTRY conflicts
// Also undef LoadImage to avoid conflict with ImageManager::LoadImage
#include <windows.h>
#undef LoadImage
#include <GL/gl.h>

#ifndef GL_CLAMP_TO_EDGE
#define GL_CLAMP_TO_EDGE 0x812F
#endif

#include "image_manager.h"
#include "log_system.h"

void ImageManager::AddImage(const std::string& filePath) {
    for (const auto& img : m_Images) {
        if (img.filePath == filePath) {
            LogSystem::Warn(u8"图片已导入: " + filePath);
            return;
        }
    }

    ImageEntry entry;
    entry.filePath = filePath;
    entry.fileName = std::filesystem::path(filePath).filename().string();
    entry.fileExt  = std::filesystem::path(filePath).extension().string();

    try {
        entry.fileSize = std::filesystem::file_size(filePath);
    } catch (...) {
        entry.fileSize = 0;
    }

    if (LoadImage(entry)) {
        m_Images.push_back(std::move(entry));
        LogSystem::Info(u8"已导入: " + entry.fileName +
            " (" + std::to_string(entry.width) + "x" + std::to_string(entry.height) + ")");
    }
}

void ImageManager::AddImages(const std::vector<std::string>& filePaths) {
    for (const auto& path : filePaths) {
        AddImage(path);
    }
}

void ImageManager::RemoveImage(size_t index) {
    if (index >= m_Images.size()) return;
    if (m_Images[index].textureLoaded) {
        glDeleteTextures(1, &m_Images[index].textureId);
    }
    std::string name = m_Images[index].fileName;
    m_Images.erase(m_Images.begin() + index);
    LogSystem::Info(u8"已移除: " + name);
}

void ImageManager::ClearAll() {
    ReleaseTextures();
    m_Images.clear();
    LogSystem::Info(u8"已清空所有图片");
}

const std::vector<ImageEntry>& ImageManager::GetImages() const {
    return m_Images;
}

size_t ImageManager::GetCount() const {
    return m_Images.size();
}

void ImageManager::ReleaseTextures() {
    for (auto& img : m_Images) {
        if (img.textureLoaded) {
            glDeleteTextures(1, &img.textureId);
            img.textureLoaded = false;
        }
    }
}

ImageManager::~ImageManager() {
    ReleaseTextures();
}

bool ImageManager::LoadImage(ImageEntry& entry) {
    int w, h, ch;
    unsigned char* data = stbi_load(entry.filePath.c_str(), &w, &h, &ch, 0);
    if (!data) {
        LogSystem::Error(u8"加载失败: " + entry.fileName + " (" + stbi_failure_reason() + ")");
        return false;
    }

    entry.width    = w;
    entry.height   = h;
    entry.channels = ch;

    // Downscale to max 512px on longest side for texture upload
    const int maxTex = 512;
    int texW = w, texH = h;
    if (w > maxTex || h > maxTex) {
        float scale = (float)maxTex / (float)(w > h ? w : h);
        texW = (int)(w * scale);
        texH = (int)(h * scale);
    }

    // Nearest-neighbor downscale to RGBA
    unsigned char* rgba = (unsigned char*)malloc(texW * texH * 4);
    if (!rgba) {
        stbi_image_free(data);
        LogSystem::Error(u8"内存不足，无法加载: " + entry.fileName);
        return false;
    }

    for (int y = 0; y < texH; y++) {
        for (int x = 0; x < texW; x++) {
            int srcX = (int)(x * (float)w / texW);
            int srcY = (int)(y * (float)h / texH);
            srcX = (srcX < w) ? srcX : w - 1;
            srcY = (srcY < h) ? srcY : h - 1;
            int si = (srcY * w + srcX) * ch;
            int di = (y * texW + x) * 4;
            rgba[di + 0] = data[si + 0];
            rgba[di + 1] = data[si + 1];
            rgba[di + 2] = data[si + 2];
            rgba[di + 3] = (ch >= 4) ? data[si + 3] : 255;
        }
    }
    stbi_image_free(data);

    // Upload to OpenGL
    GLuint texId;
    glGenTextures(1, &texId);
    glBindTexture(GL_TEXTURE_2D, texId);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, texW, texH, 0, GL_RGBA, GL_UNSIGNED_BYTE, rgba);
    glBindTexture(GL_TEXTURE_2D, 0);
    free(rgba);

    entry.textureId = texId;
    entry.textureLoaded = true;
    return true;
}
