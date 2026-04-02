import React from "react";
import "/src/assets/folder-open-solid-full.svg";
import FileUpload from "../lib/FileUpload";



export default function CenterPanel() {
  return (
    <div>
      <div className="outer-panel">
        <FileUpload className="inner-panel"/>
      </div>
    </div>
  );
}