#pragma once
#include <string>
#include <vector>
#include <filesystem>

struct ImageEntry {
    std::string  filePath;
    std::string  fileName;
    std::string  fileExt;
    size_t       fileSize   = 0;
    int          width      = 0;
    int          height     = 0;
    int          channels   = 0;
    unsigned int textureId  = 0;   // OpenGL texture ID
    bool         textureLoaded = false;
};

class ImageManager {
public:
    void AddImage(const std::string& filePath);
    void AddImages(const std::vector<std::string>& filePaths);
    void RemoveImage(size_t index);
    void ClearAll();

    const std::vector<ImageEntry>& GetImages() const;
    size_t GetCount() const;

    void ReleaseTextures();
    ~ImageManager();

private:
    std::vector<ImageEntry> m_Images;

    bool LoadImage(ImageEntry& entry);
    bool CreateThumbnailTexture(ImageEntry& entry, const unsigned char* data, int w, int h, int channels);
};
