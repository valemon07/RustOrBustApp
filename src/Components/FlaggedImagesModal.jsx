import React, { useState, useEffect } from "react";
import "./FlaggedImagesModal.css";

export default function FlaggedImagesModal({ flaggedImages, onClose }) {
  const [selectedImage, setSelectedImage] = useState(null);
  const [imageViewerOpen, setImageViewerOpen] = useState(false);
  const [imageDataUrl, setImageDataUrl] = useState(null);
  const [loadingImage, setLoadingImage] = useState(false);

  if (!flaggedImages || flaggedImages.length === 0) {
    return null;
  }

  const handleImageClick = async (filepath) => {
    setLoadingImage(true);
    setSelectedImage(filepath);
    try {
      // Try to load image using IPC API first (for Electron app)
      if (window.electronAPI && window.electronAPI.readImageAsDataUrl) {
        const dataUrl = await window.electronAPI.readImageAsDataUrl(filepath);
        setImageDataUrl(dataUrl);
      } else {
        // Fall back to direct URL for web (or file:// URLs)
        setImageDataUrl(filepath);
      }
    } catch (err) {
      console.error("Error loading image:", err);
      // Try using file:// URL as fallback
      setImageDataUrl(`file://${filepath}`);
    } finally {
      setLoadingImage(false);
      setImageViewerOpen(true);
    }
  };

  const handleCloseViewer = () => {
    setImageViewerOpen(false);
    setSelectedImage(null);
    setImageDataUrl(null);
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-content" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h2>⚠️ Flagged Images Detected</h2>
          <button className="close-button" onClick={onClose}>✕</button>
        </div>

        <div className="modal-body">
          <p className="flagged-count">
            {flaggedImages.length} image{flaggedImages.length !== 1 ? "s" : ""} flagged during analysis
          </p>

          <div className="flagged-list">
            {flaggedImages.map((flaggedItem, index) => (
              <div key={index} className="flagged-item">
                <div className="flagged-header">
                  <button
                    className="filename-button"
                    onClick={() => handleImageClick(flaggedItem.filepath)}
                    title="Click to view image"
                    disabled={loadingImage}
                  >
                    📄 {flaggedItem.filename}
                  </button>
                  <span className="badge">{flaggedItem.rejectionReasons.length} issue{flaggedItem.rejectionReasons.length !== 1 ? "s" : ""}</span>
                </div>

                <div className="rejection-reasons">
                  {flaggedItem.rejectionReasons.map((reason, idx) => (
                    <div key={idx} className="reason-item">
                      <span className="rule-tag">{reason.rule}</span>
                      <span className="reason-text">{reason.detail}</span>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="modal-footer">
          <button className="close-modal-button" onClick={onClose}>
            Close
          </button>
        </div>

        {imageViewerOpen && selectedImage && (
          <div className="image-viewer-overlay" onClick={handleCloseViewer}>
            <div className="image-viewer" onClick={(e) => e.stopPropagation()}>
              <button className="viewer-close-button" onClick={handleCloseViewer}>✕</button>
              {loadingImage ? (
                <div className="viewer-loading">Loading image...</div>
              ) : imageDataUrl ? (
                <img src={imageDataUrl} alt="Flagged" className="viewer-image" />
              ) : (
                <div className="viewer-error">Failed to load image</div>
              )}
              <p className="viewer-filename">
                {flaggedImages.find(f => f.filepath === selectedImage)?.filename}
              </p>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
