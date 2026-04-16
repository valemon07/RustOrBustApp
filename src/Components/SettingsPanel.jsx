import React, { useContext, useState } from 'react';
import { SettingsContext } from '../contexts/SettingsContext';
import './SettingsPanel.css';

export default function SettingsPanel({ onClose }) {
  const { 
    settings, 
    updateSetting, 
    resetToDefaults, 
    usingDefaultPerSetting, 
    toggleSettingDefault,
    DEFAULT_SETTINGS,
  } = useContext(SettingsContext);

  // Track local input values and validation errors
  const [inputValues, setInputValues] = useState({});
  const [validationErrors, setValidationErrors] = useState({});

  // TODO: FIX PLACEHOLDERS
  const settingsMetadata = [
    { key: 'largePixelAreaThreshold', label: 'Large Pit Area (µm²)', step: 100, min: 0, max: 10000 },
    { key: 'scaleBreakpointHigh', label: 'Scale Breakpoint High (µm/px)', step: 0.1, min: 0.1, max: 10 },
    { key: 'edgeReclassificationThreshold', label: 'Edge Reclassification', step: 0.01, min: 0, max: 1 },
    { key: 'surfacePitDarknessThreshold', label: 'Surface Pit Darkness', step: 0.01, min: 0, max: 1 },
    { key: 'exposureGamma', label: 'Exposure Constant', step: 0.1, min: 0, max: 5}
  ];

  const getInputValue = (key) => {
    return inputValues[key] !== undefined ? inputValues[key] : settings[key];
  };

  const validateValue = (value, min, max) => {
    if (value === '' || value === null) return null;
    const num = parseFloat(value);
    if (num < min) return `Value cannot be less than ${min}`;
    if (num > max) return `Value cannot be greater than ${max}`;
    return null;
  };

  const handleInputChange = (key, value) => {
    setInputValues(prev => ({ ...prev, [key]: value }));
    // Clear error while user is typing
    if (validationErrors[key]) {
      setValidationErrors(prev => ({ ...prev, [key]: null }));
    }
  };

  const handleInputBlur = (key, value, min, max) => {
    if (value === '' || value === null) {
      // Reset to default if empty
      updateSetting(key, DEFAULT_SETTINGS[key]);
      setInputValues(prev => ({ ...prev, [key]: undefined }));
      setValidationErrors(prev => ({ ...prev, [key]: null }));
    } else {
      const error = validateValue(value, min, max);
      if (error) {
        setValidationErrors(prev => ({ ...prev, [key]: error }));
      } else {
        updateSetting(key, value);
        setInputValues(prev => ({ ...prev, [key]: undefined }));
        setValidationErrors(prev => ({ ...prev, [key]: null }));
      }
    }
  };

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
          {settingsMetadata.map(({ key, label, step, min, max }) => (
            <div key={key} className="setting-item">
              <div className="setting-item-left">
                <div className="setting-item-info">
                  <label htmlFor={key}>{label}</label>
                  <span className="setting-default-hint">
                    Default: {DEFAULT_SETTINGS[key]} | Min: {min} | Max: {max}
                  </span>
                </div>
              </div>
              <div className="setting-item-right">
                <div className="input-wrapper">
                  <input
                    id={key}
                    type="number"
                    value={getInputValue(key)}
                    onChange={(e) => handleInputChange(key, e.target.value)}
                    onBlur={(e) => handleInputBlur(key, e.target.value, min, max)}
                    placeholder={`${DEFAULT_SETTINGS[key]}`}
                    step={step}
                    min={min}
                    max={max}
                    aria-describedby={`${key}-default`}
                    className={validationErrors[key] ? 'input-error' : ''}
                  />
                  {validationErrors[key] && (
                    <span className="validation-error">{validationErrors[key]}</span>
                  )}
                </div>
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