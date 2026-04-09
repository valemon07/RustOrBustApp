import * as React from "react";
import "./CenterPanel.css";
import FileUpload from "../lib/FileUpload";

export default function CenterPanel() {
  const containerRef = React.useRef(null);
  const dragCounterRef = React.useRef(0);
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
    dragCounterRef.current += 1;
    setDragging(true);
  };
  const handleDragOver = (e) => {
    e.preventDefault();
    e.stopPropagation();
    e.dataTransfer.dropEffect = "copy";
  };
  const handleDragLeave = (e) => {
    e.preventDefault();
    e.stopPropagation();
    dragCounterRef.current = Math.max(0, dragCounterRef.current - 1);
    if (dragCounterRef.current === 0) {
      setDragging(false);
    }
  };
  const handleDrop = (e) => {
    e.preventDefault();
    e.stopPropagation();
    dragCounterRef.current = 0;
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
        aria-label={isDragging ? "File upload area — drag files here" : "File upload area — click or drop files here"}
        onClick={openFileInput}
        onKeyDown={onKeyDown}
        onDragEnter={handleDragEnter}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
      >
        <div className="panel-header">
          <div className="panel-title">{isDragging ? "Drag here." : "Upload Files"}</div>
        </div>

        <FileUpload className="inner-panel" isDragging={isDragging} />

        {/* <div className="panel-hint">Click to select files or drag & drop them here</div>*/}
      </div>
    </div>
  );
}