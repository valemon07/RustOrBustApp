import React from "react";

export default function FileUpload({ className }) {
  
  // Function to send files to the backend
  // Takes in a files array, which could be a list of filePaths or Files
  const sendFiles = async (files) => {
    // FormData is used to send files in a POST request
    const formData = new FormData(); 
    
    for (const entry of files) {
      // Used for drag-and-drop, where entry is a File object

      if (entry instanceof File) {
        formData.append('image', entry, entry.name);
      } else {
        // Used for click-to-upload, where entry is a file path string

        const file = new File([entry], entry.split("/").pop());
        //const file = await window.electronAPI.readFile(filePath);
        formData.append('image', file, file.name);
      }
    }

    try {
      // Send the files to the backend at the /analyze endpoint
      const response = await fetch("http://localhost:5001/analyze", {
        method: "POST",
        body: formData,
      });

      // Test results from the simple backend
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "results.csv";
      a.click();
    } catch (e) {
      console.log("Error! " + e);
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
      sendFiles(result.filePaths);
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
      sendFiles(draggedFiles)
    }
  }

  return (
    <div
      className={className}
      onClick={clickHandler}
      onDragOver={onDragOver}
      onDrop={onDrop}>
      <img
        src="/src/assets/folder-open-solid-full.svg"
        alt="Folder Icon"
        style={{ width: "70px", height: "70px", marginBottom: "10px" }}
      />
      <div>Drag and drop files here, or click to browse your computer.</div>
    </div>
  );
}
