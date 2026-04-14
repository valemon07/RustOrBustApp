import React, { useContext } from 'react';
import { SettingsContext } from '../contexts/SettingsContext';
import './SettingsPanel.css';

export default function SettingsPanel({ onClose }) {
  const { 
    settings, 
    updateSetting, 
    resetToDefaults, 
    usingDefaultPerSetting, 
    toggleSettingDefault,
    DEFAULT_SETTINGS 
  } = useContext(SettingsContext);

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
            <img
              src="src/assets/arrow-left-solid-full.svg"
              alt="Back Icon"
              className="back-icon"
            />
            Back
          </button>
        )}
        <h2>Pipeline Settings</h2>
      </div>

      <div className="settings-content">
        <div className="settings-list">
          {settingsMetadata.map(({ key, label, step, min }) => (
            <div key={key} className="setting-item">
              <div className="setting-item-left">
                <div className="setting-item-info">
                  <label htmlFor={key}>{label}</label>
                  <span className="setting-default-hint">
                    Default: {DEFAULT_SETTINGS[key]}
                  </span>
                </div>
              </div>
              <div className="setting-item-right">
                <input
                  id={key}
                  type="number"
                  value={settings[key]}
                  onChange={(e) => updateSetting(key, e.target.value)}
                  placeholder={`${DEFAULT_SETTINGS[key]}`}
                  step={step}
                  min={min}
                  aria-describedby={`${key}-default`}
                />
                <button
                  className={`use-default-button ${usingDefaultPerSetting[key] ? 'active' : ''}`}
                  onClick={() => toggleSettingDefault(key)}
                  title={usingDefaultPerSetting[key] ? 'Using default value' : 'Restore default'}
                  aria-label={`Toggle default for ${label}`}
                >
                  Default
                </button>
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className="settings-actions">
        <button className="settings-reset" onClick={resetToDefaults}>
          Reset All to Defaults
        </button>
      </div>
    </div>
  );
}