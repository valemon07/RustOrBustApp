import * as React from "react";
import "./CenterPanel.css";
import FileUpload from "../lib/FileUpload";
import { useContext } from "react";
import { SettingsContext } from "../contexts/SettingsContext";
import SettingsPanel from "./SettingsPanel";

export default function CenterPanel({ showSettings, setShowSettings }) {
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

  const { exportSettings } = useContext(SettingsContext);

  return (
    <div className="center-panel-wrapper">
      {showSettings ? (
        <SettingsPanel onClose={() => setShowSettings(false)} />
      ) : (
        <div className="upload-view-wrapper">
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
          </div>

          <button
            className="settings-icon-button"
            onClick={() => setShowSettings(true)}
            title="Pipeline settings"
            aria-label="Open pipeline settings"
          >
            <img
              src="src/assets/gear-solid-full.svg"
              alt="Settings Icon"
              className="settings-icon"
            />
            <span className="settings-button-label">Pipeline Settings</span>
          </button>
        </div>
      )}
    </div>
  );
}