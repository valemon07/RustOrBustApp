import React from 'react';
import "/src/assets/folder-open-solid-full.svg"

const FileUpload = ({className, onClick}) => {
    return (
        <div className={className} onClick={onClick}>
            <img src="/src/assets/folder-open-solid-full.svg" alt="Folder Icon" style={{ width: '70px', height: '70px', marginBottom: '10px' }} />
            <div>
                Drag and drop files here, or click to browse your computer.
            </div>
        </div>
    );
}

export default function CenterPanel() {
    return (
        <div>
            <div className="outer-panel">
                <FileUpload className="inner-panel" onClick={() => alert('File upload functionality will be implemented here.')}/>
            </div>
        </div>
    );
}
