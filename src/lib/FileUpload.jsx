import React, { useContext, useState } from "react";
import ReactDOM from "react-dom";
import FlaggedImagesModal from "../Components/FlaggedImagesModal";
import { SettingsContext } from "../contexts/SettingsContext";
import folderIcon from "../assets/folder-open-solid-full.svg";

const BACKEND_BASE_URL = "http://localhost:5001";
const ANALYZE_URL = `${BACKEND_BASE_URL}/analyze`;
const FLAGGED_URL = `${BACKEND_BASE_URL}/flagged-images`;

export default function FileUpload({ className, isDragging = false }) {
  const { settings } = useContext(SettingsContext);
  const [flaggedImages, setFlaggedImages] = useState([]);
  const [showModal, setShowModal] = useState(false);
  const [isProcessing, setIsProcessing] = useState(false);

  /**
   * Core handler — receives either:
   *   - an array of absolute path strings  (from the Electron file dialog)
   *   - a FileList / File[]               (from drag-and-drop; Electron gives each File a .path)
   */
  const handleFiles = async (fileList) => {
    // Normalise to absolute path strings
    const paths = Array.from(fileList)
      .map((f) => (typeof f === "string" ? f : f.path))
      .filter(Boolean);

    if (paths.length === 0) return;

    setIsProcessing(true);
    try {
      const res = await fetch(ANALYZE_URL, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ paths, settings }),
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({ error: `HTTP ${res.status}` }));
        console.error("Analysis failed:", err);
        return;
      }

      const zipBlob = await res.blob();

      // Derive filename from Content-Disposition header, fallback to timestamp
      const disposition = res.headers.get("Content-Disposition") || "";
      const match = disposition.match(/filename=([^\s;]+)/);
      const zipName = match ? match[1] : `rust_or_bust_${Date.now()}.zip`;

      // Trigger save-as dialog
      const url = URL.createObjectURL(zipBlob);
      const a = document.createElement("a");
      a.href = url;
      a.download = zipName;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);

      // Check for flagged images
      try {
        const flagRes = await fetch(FLAGGED_URL);
        if (flagRes.ok) {
          const data = await flagRes.json();
          if (data.flaggedImages?.length > 0) {
            setFlaggedImages(
              data.flaggedImages.map((item) => ({
                filename: item.filename,
                filepath: item.filepath || item.filename,
                rejectionReasons: item.reasons || [
                  { rule: "Unknown", detail: item.reason || "Flagged during analysis" },
                ],
              }))
            );
            setShowModal(true);
          }
        }
      } catch (err) {
        console.error("Error fetching flagged images:", err);
      }
    } catch (err) {
      console.error("Upload error:", err);
    } finally {
      setIsProcessing(false);
    }
  };

  // Electron file-dialog picker
  const clickHandler = async () => {
    const result = await window.electronAPI.openFile();
    if (!result.canceled && result.filePaths.length > 0) {
      handleFiles(result.filePaths);
    }
  };

  // Drag-and-drop
  const onDragOver = (e) => {
    e.preventDefault();
    e.stopPropagation();
    e.dataTransfer.dropEffect = "copy";
  };

  const onDrop = (e) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.dataTransfer.files?.length > 0) {
      handleFiles(e.dataTransfer.files);
    }
  };

  const uploadCopy = isProcessing
    ? "Analyzing…"
    : isDragging
    ? "Drag here."
    : "Drop files here or click to browse";

  const uploadSubcopy = isProcessing
    ? "Please wait while the pipeline runs"
    : isDragging
    ? "Release to start analysis"
    : "Supports multiple images and exports one CSV";

  return (
    <>
      {showModal && ReactDOM.createPortal(
        <FlaggedImagesModal
          flaggedImages={flaggedImages}
          onClose={() => {
            setShowModal(false);
            setFlaggedImages([]);
          }}
        />,
        document.body
      )}
      <div
        className={`${className} ${isDragging ? "dragging" : ""} ${isProcessing ? "processing" : ""}`}
        onClick={isProcessing ? undefined : clickHandler}
        onDragOver={isProcessing ? undefined : onDragOver}
        onDrop={isProcessing ? undefined : onDrop}
      >
        <img
          src={folderIcon}
          alt="Folder Icon"
          className="upload-icon"
        />
        <p className="upload-copy">{uploadCopy}</p>
        <p className="upload-subcopy">{uploadSubcopy}</p>
      </div>
    </>
  );
}
