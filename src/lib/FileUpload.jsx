import React, { useState } from "react";
import FlaggedImagesModal from "../Components/FlaggedImagesModal";

export default function FileUpload({ className, isDragging = false }) {
  const [flaggedImages, setFlaggedImages] = useState([]);
  const [showModal, setShowModal] = useState(false);
  
  // Function to send files to the backend
  // Takes in a files array, which could be a list of filePaths or Files
  const sleep = (ms) => new Promise((res) => setTimeout(res, ms));
  
  /**
   * Upload files in parallel with concurrency, optional batching, retries and progress.
   * - files: FileList | File[] | array of file paths (if using existing path behavior)
   * - options: { concurrency, batchSize, maxRetries, onProgress, endpoint }
   *
   * Behavior:
   * - If batchSize === 1: each request contains a single file (many parallel requests).
   * - If batchSize > 1: groups of `batchSize` files are sent in one request.
   * - Response bodies are read as text and concatenated into one CSV. Headers after the first are stripped.
   */
  async function uploadFilesParallel(rawFiles, options = {}) {
    const {
      concurrency = 6,
      batchSize = 1,
      maxRetries = 2,
      onProgress = () => {},
      endpoint = "http://localhost:5001/analyze",
    } = options;
  
    // normalize to array of File objects or file-path strings (preserves your current behavior)
    const files = Array.from(rawFiles);
  
    // create batches: each batch is an array of file or path entries
    const batches = [];
    for (let i = 0; i < files.length; i += batchSize) {
      batches.push(files.slice(i, i + batchSize));
    }
  
    let completed = 0;
    const results = new Array(batches.length);
  
    // worker function: uploads one batch, with retries
    const uploadBatch = async (batch, batchIndex) => {
      let attempt = 0;
      while (true) {
        try {
          const formData = new FormData();
          for (const entry of batch) {
            if (entry instanceof File) {
              formData.append("image", entry, entry.name);
            } else {
              // keep behavior for path strings (existing electron API). This creates a placeholder File:
              const filePath = entry;
              const file = new File([filePath], filePath.split("/").pop());
              formData.append("image", file, file.name);
            }
          }

          // TODO: validate with backend
          if(options.settings) {
            formData.append("settings", JSON.stringify(options.settings))
          }
  
          const res = await fetch(endpoint, {
            method: "POST",
            body: formData,
          });
  
          // if you expect binary results, use res.blob() — here we read text (CSV) and combine later
          if (!res.ok) throw new Error(`HTTP ${res.status}`);
          const text = await res.text();
          results[batchIndex] = text;
          completed += batch.length;
          onProgress({ completed, total: files.length, batchIndex });
          return;
        } catch (err) {
          attempt += 1;
          if (attempt > maxRetries) {
            // store an empty string or error marker
            results[batchIndex] = "";
            completed += batch.length;
            onProgress({ completed, total: files.length, batchIndex, error: err });
            return;
          }
          // exponential backoff
          await sleep(200 * Math.pow(2, attempt));
        }
      }
    };
  
    // simple promise pool
    let index = 0;
    const workers = Array.from({ length: Math.min(concurrency, batches.length) }).map(
      async () => {
        while (index < batches.length) {
          const i = index++;
          await uploadBatch(batches[i], i);
        }
      }
    );
  
    await Promise.all(workers);
  
    // combine CSV texts, attempt to keep only first header
    const nonEmpty = results.filter(Boolean);
    if (nonEmpty.length === 0) return null;
  
    const combined = nonEmpty.reduce((acc, text, idx) => {
      const lines = text.split(/\r?\n/).filter(Boolean);
      if (idx === 0) return lines.join("\n");
      // drop the first line (header) of subsequent responses if it looks like a header
      if (lines.length > 0) {
        lines.shift();
        return acc + "\n" + lines.join("\n");
      }
      return acc;
    }, "");
  
    // return combined CSV text (caller can save it)
    return combined;
  }
  
  // Parse CSV to extract flagged images
  const parseFlaggedImages = (csvText) => {
    if (!csvText) return [];

    const lines = csvText.split(/\r?\n/).filter(line => line.trim());
    if (lines.length < 2) return [];

    // Find header row
    const headerLine = lines[0];
    const headers = headerLine.split(",").map(h => h.trim());
    
    const filenameIndex = headers.indexOf("filename");
    const rejectionDetailIndex = headers.indexOf("rejection_detail");
    const failedRulesIndex = headers.indexOf("failed_rules");

    if (filenameIndex === -1) return [];

    // Group by filename
    const flaggedMap = {};
    for (let i = 1; i < lines.length; i++) {
      const line = lines[i];
      if (!line.trim()) continue;

      // Simple CSV parsing - handles basic comma separation
      const parts = line.split(",");
      if (parts.length < 1) continue;

      const filename = parts[filenameIndex]?.trim() || "";
      const rejectionDetail = parts[rejectionDetailIndex]?.trim() || "";
      const failedRules = parts[failedRulesIndex]?.trim() || "";

      if (filename && rejectionDetail) {
        if (!flaggedMap[filename]) {
          flaggedMap[filename] = [];
        }
        
        // Parse failed rules to extract rule names
        const rules = failedRules.split(";").map(r => r.trim()).filter(Boolean);
        rules.forEach(rule => {
          flaggedMap[filename].push({
            rule: rule,
            detail: rejectionDetail
          });
        });
      }
    }

    // Convert to array with file paths
    return Object.entries(flaggedMap).map(([filename, rejectionReasons]) => ({
      filename,
      filepath: filename, // This will be updated by backend to provide actual path
      rejectionReasons
    }));
  };

  // call for FileList from drop or array of File objects
  const handleDropFiles = async (fileList) => {
    const combinedCsv = await uploadFilesParallel(fileList, {
      concurrency: 8,
      batchSize: 1,        // 1 = one file per request; increase to batch multiple files per request
      maxRetries: 3,
      endpoint: "http://localhost:5001/analyze",
      onProgress: ({ completed, total }) => {
        console.log(`Uploaded ${completed}/${total}`);
      },
    });
  
    if (combinedCsv) {
      // Parse flagged images from CSV
      const flagged = parseFlaggedImages(combinedCsv);
      
      // Also fetch flagged images info from backend
      try {
        const response = await fetch("http://localhost:5001/flagged-images");
        if (response.ok) {
          const data = await response.json();
          if (data.flaggedImages && data.flaggedImages.length > 0) {
            // Use backend flagged images if available
            const enhancedFlagged = data.flaggedImages.map(item => ({
              filename: item.filename,
              filepath: item.filename, // Will be updated to actual path
              rejectionReasons: item.reasons || [{ rule: "Unknown", detail: item.reason || "Flagged during analysis" }]
            }));
            setFlaggedImages(enhancedFlagged);
            setShowModal(true);
          } else if (flagged.length > 0) {
            // Fall back to CSV parsing if no backend data
            setFlaggedImages(flagged);
            setShowModal(true);
          }
        } else if (flagged.length > 0) {
          // Fall back to CSV parsing
          setFlaggedImages(flagged);
          setShowModal(true);
        }
      } catch (err) {
        console.error("Error fetching flagged images:", err);
        // Fall back to CSV parsing
        if (flagged.length > 0) {
          setFlaggedImages(flagged);
          setShowModal(true);
        }
      }

      // Download CSV
      const blob = new Blob([combinedCsv], { type: "text/csv" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "results.csv";
      a.click();
    } else {
      console.log("No results returned.");
    }
  };
  
  
  // Handles clicks from on the FileUpload component, 
  // which opens a file dialog and sends the selected files to the backend
  const clickHandler = async () => {
    // console.log("Clicked!");
    const result = await window.electronAPI.openFile();
    if (!result.canceled) {
      // Prints result.filePaths (array) to test
      // console.log("Selected files:", result.filePaths);
      handleDropFiles(result.filePaths);
    }
  };
  
  // Both of these functions are used for drag-and-drop functionality, 
  // which sends the dragged files to the backend
  
  const onDragOver = (e) => {
    e.preventDefault();
    e.stopPropagation();
    e.dataTransfer.dropEffect = "copy";
  };
  
  const onDrop = async (e) => {
    e.preventDefault();
    e.stopPropagation();
    const draggedFiles = e.dataTransfer.files;
    if (draggedFiles && draggedFiles.length > 0) {
      handleDropFiles(draggedFiles)
    }
  }

  return (
    <>
      {showModal && (
        <FlaggedImagesModal 
          flaggedImages={flaggedImages} 
          onClose={() => setShowModal(false)}
        />
      )}
      <div
        className={`${className} ${isDragging ? "dragging" : ""}`}
        onClick={clickHandler}
        onDragOver={onDragOver}
        onDrop={onDrop}>
        <img
          src="/src/assets/folder-open-solid-full.svg"
          alt="Folder Icon"
          className="upload-icon"
        />
        <p className="upload-copy">{isDragging ? "Drag here." : "Drop files here or click to browse"}</p>
        <p className="upload-subcopy">
          {isDragging ? "Release to start analysis" : "Supports multiple images and exports one CSV"}
        </p>
      </div>
    </>
  );
}
