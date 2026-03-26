import React from "react";
import "/src/assets/folder-open-solid-full.svg";


const FileUpload = ({ className, onClick }) => {
  return (
    <div className={className} onClick={onClick}>
      <img
        src="/src/assets/folder-open-solid-full.svg"
        alt="Folder Icon"
        style={{ width: "70px", height: "70px", marginBottom: "10px" }}
      />
      <div>Drag and drop files here, or click to browse your computer.</div>
    </div>
  );
};

const clickHandler = async () => {
  const result = await window.electronAPI.openFile();
  if (!result.canceled) {
    // Prints result.filePaths (array) to test
    console.log('Selected files:', result.filePaths);
    sendFiles(result.filePaths);
  }
};

const sendFiles = async (files) => {
    const formData = new FormData();

    for (const filePath of files) {
        // Convert the file path to a Blob so it can be sent over HTTP
        const response = await fetch(filePath);
        const blob = await response.blob();
        const fileName = filePath.split('/').pop(); // extract filename from path
        formData.append('image', blob, fileName);
    }

    try {
        const response = await fetch('http://localhost:5001/analyze', {
            method: 'POST',
            body: formData
        });

        const blob = await response.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = 'results.csv';
        a.click();

    } catch (e) {
        console.log("Error! " + e);
    }
};


export default function CenterPanel() {
  return (
    <div>
      <div className="outer-panel">
        <FileUpload className="inner-panel" onClick={() => clickHandler()} />
      </div>
    </div>
  );
}