// image_manager.h - 图片加载、缩略图生成与纹理管理
//
// 管理导入的图片列表及其 OpenGL 缩略图纹理。
// 使用 stb_image 解码，并创建缩小（最大 512px）的纹理
// 以实现高效的 UI 预览渲染。
//
// 线程安全:
//   ImageManager 的方法不是线程安全的。所有调用必须来自
//   主线程（拥有 OpenGL 上下文的线程）。渲染管线通过 stbi_load
//   独立地以全分辨率重新加载图片。
//
#pragma once
#include <string>
#include <vector>
#include <filesystem>

// 单张导入图片的元数据，包含其 OpenGL 纹理。
struct ImageEntry {
    std::string  filePath;
    std::string  fileName;
    std::string  fileExt;
    size_t       fileSize   = 0;
    int          width      = 0;       // 原始图片宽度
    int          height     = 0;       // 原始图片高度
    int          channels   = 0;       // 颜色通道 (1=灰度, 3=RGB, 4=RGBA)
    unsigned int textureId  = 0;       // 缩略图的 OpenGL 纹理 ID
    bool         textureLoaded = false;
};

class ImageManager {
public:
    // 添加单张图片（按文件路径去重）。
    void AddImage(const std::string& filePath);

    // 添加多张图片（便捷封装）。
    void AddImages(const std::vector<std::string>& filePaths);

    // 按索引移除单张图片（同时删除其纹理）。
    void RemoveImage(size_t index);

    // 移除所有图片并释放所有纹理。
    void ClearAll();

    // 获取图片列表的只读访问。
    const std::vector<ImageEntry>& GetImages() const;

    // 获取已导入图片的数量。
    size_t GetCount() const;

    // 释放所有 OpenGL 纹理（在销毁 GL 上下文之前调用）。
    void ReleaseTextures();

    ~ImageManager();

private:
    std::vector<ImageEntry> m_Images;

    // 加载图片文件，解码，创建缩略图纹理。
    // 填充 entry.width/height/channels/textureId/textureLoaded。
    bool LoadImage(ImageEntry& entry);

    // 从图片数据创建缩小的 RGBA OpenGL 纹理。
    bool CreateThumbnailTexture(ImageEntry& entry, const unsigned char* data, int w, int h, int channels);
};
