import React from 'react';

const FileUpload = ({className, onClick}) => {
    return (
        <div className={className} onClick={onClick}>Upload File</div>
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
