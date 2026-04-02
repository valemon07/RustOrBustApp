import React from "react";
import "/src/assets/folder-open-solid-full.svg";
import FileUpload from "../lib/FileUpload";

// const FileUpload = ({ className, onClick }) => {
//   return (
//     <div className={className} onClick={onClick}>
//       <img
//         src="/src/assets/folder-open-solid-full.svg"
//         alt="Folder Icon"
//         style={{ width: "70px", height: "70px", marginBottom: "10px" }}
//       />
//       <div>Drag and drop files here, or click to browse your computer.</div>
//     </div>
//   );
// };

// const clickHandler = async () => {
//   const result = await window.electronAPI.openFile();
//   if (!result.canceled) {
//     // Prints result.filePaths (array) to test
//     console.log('Selected files:', result.filePaths);
//     sendFiles(result.filePaths);
//   }
// };



export default function CenterPanel() {
  return (
    <div>
      <div className="outer-panel">
        <FileUpload className="inner-panel"/>
      </div>
    </div>
  );
}