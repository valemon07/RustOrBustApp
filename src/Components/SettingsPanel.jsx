import React, { useContext } from 'react';
import { SettingsContext } from '../contexts/SettingsContext';
import './SettingsPanel.css';

export default function SettingsPanel({ onClose }) {
  const { settings, updateSetting, resetToDefaults, useDefaults, setUseDefaults } = useContext(SettingsContext);

  const settingsMetadata = [
    { key: 'largePixelAreaThreshold', label: 'Large Pit Area (µm²)', step: 100, min: 0 },
    { key: 'scaleBreakpointHigh', label: 'Scale Breakpoint High (µm/px)', step: 0.1, min: 0.1 },
    { key: 'edgeReclassificationThreshold', label: 'Edge Reclassification', step: 0.01, min: 0 },
    { key: 'surfacePitDarknessThreshold', label: 'Surface Pit Darkness', step: 0.01, min: 0 },
  ];

  return (
    <div className="settings-panel">
      <div className="settings-header">
        {onClose && (
          <button
            className="settings-back-button"
            onClick={onClose}
            title="Back to upload"
            aria-label="Back to upload"
          >
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M19 12H5M12 19l-7-7 7-7"></path>
            </svg>
            Back
          </button>
        )}
        <h2>Pipeline Settings</h2>
      </div>

      <div className="settings-content">
        <div className="settings-toggle">
          <label>
            <input
              type="checkbox"
              checked={useDefaults}
              onChange={(e) => setUseDefaults(e.target.checked)}
            />
            Use Backend Defaults
          </label>
        </div>

        {!useDefaults && (
          <div className="settings-grid">
            {settingsMetadata.map(({ key, label, step, min }) => (
              <div key={key} className="setting-field">
                <label htmlFor={key}>{label}</label>
                <input
                  id={key}
                  type="number"
                  value={settings[key]}
                  onChange={(e) => updateSetting(key, e.target.value)}
                  step={step}
                  min={min}
                />
              </div>
            ))}
          </div>
        )}
      </div>

      {!useDefaults && (
        <div className="settings-actions">
          <button className="settings-reset" onClick={resetToDefaults}>
            Reset to Defaults
          </button>
        </div>
      )}
    </div>
  );
}