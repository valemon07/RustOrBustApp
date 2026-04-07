import * as React from "react";
import "./CenterPanel.css";
import folderIcon from "/src/assets/folder-open-solid-full.svg";
import FileUpload from "../lib/FileUpload";

export default function CenterPanel() {
  const containerRef = React.useRef(null);
  const [isDragging, setDragging] = React.useState(false);

  const openFileInput = () => {
    if (!containerRef.current) return;
    const input = containerRef.current.querySelector('input[type="file"]');
    if (input) input.click();
  };

  const onKeyDown = (e) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      openFileInput();
    }
  };

  const handleDragEnter = (e) => {
    e.preventDefault();
    e.stopPropagation();
    setDragging(true);
  };
  const handleDragOver = (e) => {
    e.preventDefault();
    e.stopPropagation();
  };
  const handleDragLeave = (e) => {
    e.preventDefault();
    e.stopPropagation();
    setDragging(false);
  };
  const handleDrop = (e) => {
    e.preventDefault();
    e.stopPropagation();
    setDragging(false);
    // Let FileUpload handle dropped files, or forward them here if needed.
  };

  return (
    <div className="center-panel-wrapper">
      <div
        ref={containerRef}
        className={`outer-panel ${isDragging ? "dragging" : ""}`}
        role="button"
        tabIndex={0}
        aria-label="File upload area — click or drop files here"
        onClick={openFileInput}
        onKeyDown={onKeyDown}
        onDragEnter={handleDragEnter}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
      >
        <div className="panel-header">
          {/* <img src={folderIcon} alt="" className="panel-icon" />*/}
          <div className="panel-title">Upload Files</div>
        </div>

        <FileUpload className="inner-panel" />

        {/* <div className="panel-hint">Click to select files or drag & drop them here</div>*/}
      </div>
    </div>
  );
}