import React, { createContext, useState } from 'react';

// Default settings 
const DEFAULT_SETTINGS = {
  largePixelAreaThreshold: 2000.0,
  scaleBreakpointHigh: 4.0,
  edgeReclassificationThreshold: 0.5,
  surfacePitDarknessThreshold: 0.3,
  exposureGamma: 1,
  customThresholds: [], // Array of floats sent to backend
};

export const SettingsContext = createContext();

export function SettingsProvider({ children }) {
  const [settings, setSettings] = useState(DEFAULT_SETTINGS);
  const [useDefaults, setUseDefaults] = useState(true);
  const [usingDefaultPerSetting, setUsingDefaultPerSetting] = useState({
    largePixelAreaThreshold: true,
    scaleBreakpointHigh: true,
    edgeReclassificationThreshold: true,
    surfacePitDarknessThreshold: true,
  });

  const updateSetting = (key, value) => {
    const parsedValue = typeof value === 'string' ? parseFloat(value) || 0 : value;
    setSettings(prev => ({
      ...prev,
      [key]: parsedValue
    }));
    
    // Auto-toggle: if value matches default, mark as using default; otherwise mark as custom
    const isDefault = parsedValue === DEFAULT_SETTINGS[key];
    setUsingDefaultPerSetting(prev => ({
      ...prev,
      [key]: isDefault
    }));
  };

  const toggleSettingDefault = (key) => {
    // Clicking the default button always restores to default
    setSettings(prev => ({
      ...prev,
      [key]: DEFAULT_SETTINGS[key]
    }));
    setUsingDefaultPerSetting(prev => ({
      ...prev,
      [key]: true
    }));
  };

  const resetToDefaults = () => {
    setSettings(DEFAULT_SETTINGS);
    setUseDefaults(true);
    setUsingDefaultPerSetting({
      largePixelAreaThreshold: true,
      scaleBreakpointHigh: true,
      edgeReclassificationThreshold: true,
      surfacePitDarknessThreshold: true,
    });
  };

  const exportSettings = () => {
    return useDefaults ? null : settings; // null signals: use backend defaults
  };

  return (
    <SettingsContext.Provider value={{
      settings,
      updateSetting,
      resetToDefaults,
      exportSettings,
      useDefaults,
      setUseDefaults,
      usingDefaultPerSetting,
      toggleSettingDefault,
      DEFAULT_SETTINGS
    }}>
      {children}
    </SettingsContext.Provider>
  );
}