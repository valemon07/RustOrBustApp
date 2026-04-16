// src/Components/FlaggedImagesModal.test.jsx
import React from "react";
import FlaggedImagesModal from "./FlaggedImagesModal";

export default function TestModal() {
  const mockFlaggedImages = [
    {
      filename: "CR3-1_pit_BF001.jpg",
      filepath: "/home/user/Documents/image1.jpg",
      rejectionReasons: [
        { rule: "R1", detail: "Area 9.88µm² < floor 10.0µm²" },
        { rule: "R3", detail: "Aspect ratio 21.44 > max 8.0" }
      ]
    },
    {
      filename: "CR3-7_overview.jpg",
      filepath: "/home/user/Documents/image2.jpg",
      rejectionReasons: [
        { rule: "R5", detail: "Area < scale-min 125.4µm²" }
      ]
    },
    {
      filename: "sample_pit.jpg",
      filepath: "/home/user/Documents/image3.jpg",
      rejectionReasons: [
        { rule: "R2", detail: "Intensity ratio outside acceptable range" },
        { rule: "R4", detail: "Solidity check failed" }
      ]
    }
  ];

  return (
    <FlaggedImagesModal
      flaggedImages={mockFlaggedImages}
      onClose={() => alert("Modal closed")}
    />
  );
}