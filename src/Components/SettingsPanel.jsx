import React, { useContext, useState } from 'react';
import { SettingsContext } from '../contexts/SettingsContext';
import './SettingsPanel.css';
import arrowIcon from '../assets/arrow-left-solid-full.svg';

export default function SettingsPanel({ onClose }) {
  const {
    settings,
    updateSetting,
    resetToDefaults,
    usingDefaultPerSetting,
    toggleSettingDefault,
    DEFAULT_SETTINGS,
  } = useContext(SettingsContext);

  const [inputValues, setInputValues] = useState({});
  const [validationErrors, setValidationErrors] = useState({});

  // Parameters the researcher is most likely to tune when an image is misflagged.
  // description: shown as a hint explaining what the parameter does and which
  //              direction tightens detection (reduces false positives).
  const settingsMetadata = [
    {
      key: 'gamma',
      label: 'Exposure Gamma',
      description: '1.0 = neutral (default). Lower values (e.g. 0.5) darken, higher values (e.g. 2.0–3.0) brighten. Set to 0 for auto contrast sweep. Adjust when the mask is poor.',
      step: 0.1,
      min: 0,
      max: 5,
    },
    {
      key: 'morph_open_kernel_px',
      label: 'Morph Open Kernel (px)',
      description: '0 = disabled. Increase to 2–4 to erase narrow dark streaks (scratches, grain lines) before pit detection. Reduces false positives from surface texture.',
      step: 1,
      min: 0,
      max: 10,
    },
    {
      key: 'r7_max_intensity_ratio',
      label: 'R7 Darkness Threshold',
      description: 'Rejects candidates brighter than this fraction of the surface mean. Default 0.85 — decrease (e.g. 0.72) to require pits to be darker, reducing false positives from faint scratches.',
      step: 0.01,
      min: 0.1,
      max: 1.0,
    },
    {
      key: 'r3_max_aspect_ratio',
      label: 'R3 Max Aspect Ratio',
      description: 'Rejects elongated scratch-like candidates. Default 8.0 — decrease (e.g. 5.0) to reject less-elongated features. Tightening helps when scratch fragments are being counted as pits.',
      step: 0.5,
      min: 1,
      max: 20,
    },
    {
      key: 'r4_min_circularity',
      label: 'R4 Min Circularity',
      description: 'Rejects irregularly shaped candidates (0 = line, 1 = perfect circle). Default 0.08 — increase (e.g. 0.12) to require rounder pits, reducing irregular noise features.',
      step: 0.01,
      min: 0,
      max: 1,
    },
    {
      key: 'r8_min_aspect_ratio',
      label: 'R8 Scratch Aspect Ratio',
      description: 'Minimum aspect ratio for the R8 orientation-based scratch rejection. Default 3.0 — decrease (e.g. 2.0) to also catch less-elongated scratch segments.',
      step: 0.1,
      min: 1,
      max: 10,
    },
  ];

  const getInputValue = (key) =>
    inputValues[key] !== undefined ? inputValues[key] : settings[key];

  const validateValue = (value, min, max) => {
    if (value === '' || value === null) return null;
    const num = parseFloat(value);
    if (isNaN(num)) return 'Must be a number';
    if (num < min) return `Cannot be less than ${min}`;
    if (num > max) return `Cannot be greater than ${max}`;
    return null;
  };

  const handleInputChange = (key, value) => {
    setInputValues(prev => ({ ...prev, [key]: value }));
    if (validationErrors[key]) {
      setValidationErrors(prev => ({ ...prev, [key]: null }));
    }
  };

  const handleInputBlur = (key, value, min, max) => {
    if (value === '' || value === null) {
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
              src={arrowIcon}
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
          {settingsMetadata.map(({ key, label, description, step, min, max }) => (
            <div key={key} className="setting-item">
              <div className="setting-item-left">
                <div className="setting-item-info">
                  <label htmlFor={key}>{label}</label>
                  <span className="setting-default-hint">{description}</span>
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
                    aria-describedby={`${key}-hint`}
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
