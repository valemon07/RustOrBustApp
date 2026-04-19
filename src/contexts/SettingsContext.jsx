import React, { createContext, useState } from 'react';

// Default settings — match the module-level constants in stage2_roi.py / stage3_pit_detection.py.
// Special sentinels:
//   gamma = 0             → auto contrast sweep (no fixed gamma)
//   morph_open_kernel_px = 0 → morphological open disabled
const DEFAULT_SETTINGS = {
  gamma: 1,
  morph_open_kernel_px: 0,
  r7_max_intensity_ratio: 0.85,
  r3_max_aspect_ratio: 8.0,
  r4_min_circularity: 0.08,
  r8_min_aspect_ratio: 3.0,
};

const ALL_SETTING_KEYS = Object.keys(DEFAULT_SETTINGS);

export const SettingsContext = createContext();

export function SettingsProvider({ children }) {
  const [settings, setSettings] = useState(DEFAULT_SETTINGS);
  const [usingDefaultPerSetting, setUsingDefaultPerSetting] = useState(
    Object.fromEntries(ALL_SETTING_KEYS.map(k => [k, true]))
  );

  const updateSetting = (key, value) => {
    const parsed = typeof value === 'string' ? parseFloat(value) : value;
    const safe   = isNaN(parsed) ? 0 : parsed;
    setSettings(prev => ({ ...prev, [key]: safe }));
    setUsingDefaultPerSetting(prev => ({
      ...prev,
      [key]: safe === DEFAULT_SETTINGS[key],
    }));
  };

  const toggleSettingDefault = (key) => {
    setSettings(prev => ({ ...prev, [key]: DEFAULT_SETTINGS[key] }));
    setUsingDefaultPerSetting(prev => ({ ...prev, [key]: true }));
  };

  const resetToDefaults = () => {
    setSettings(DEFAULT_SETTINGS);
    setUsingDefaultPerSetting(Object.fromEntries(ALL_SETTING_KEYS.map(k => [k, true])));
  };

  return (
    <SettingsContext.Provider value={{
      settings,
      updateSetting,
      resetToDefaults,
      usingDefaultPerSetting,
      toggleSettingDefault,
      DEFAULT_SETTINGS,
    }}>
      {children}
    </SettingsContext.Provider>
  );
}
