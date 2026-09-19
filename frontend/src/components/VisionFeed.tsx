import React, { useState, useEffect } from 'react';
import { Camera, Maximize2, Minimize2, RefreshCw, AlertTriangle, Layers, Focus } from 'lucide-react';
import { SceneStateData } from '../types/robosurge';

interface VisionFeedProps {
  scene: SceneStateData;
  cameraStatus: string;
  onSelectLandmark?: (name: string) => void;
}

export const VisionFeed: React.FC<VisionFeedProps> = ({ scene, cameraStatus, onSelectLandmark }) => {
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [showOverlays, setShowOverlays] = useState(true);
  const [streamError, setStreamError] = useState(false);
  const [imgKey, setImgKey] = useState(Date.now());

  const handleRefreshFeed = () => {
    setStreamError(false);
    setImgKey(Date.now());
  };

  const toggleFullscreen = () => {
    const el = document.getElementById('vision-feed-container');
    if (!el) return;
    if (!document.fullscreenElement) {
      el.requestFullscreen().catch(() => {});
      setIsFullscreen(true);
    } else {
      document.exitFullscreen().catch(() => {});
      setIsFullscreen(false);
    }
  };

  useEffect(() => {
    const handleFsChange = () => {
      setIsFullscreen(!!document.fullscreenElement);
    };
    document.addEventListener('fullscreenchange', handleFsChange);
    return () => document.removeEventListener('fullscreenchange', handleFsChange);
  }, []);

  return (
    <div 
      id="vision-feed-container"
      className={`retro-panel overflow-hidden flex flex-col transition-all shadow-sm ${
        isFullscreen ? 'fixed inset-0 z-50 bg-black p-4' : 'h-full min-h-0'
      }`}
    >
      {/* Compact Header bar */}
      <div className="retro-header flex items-center justify-between px-2.5 py-1 select-none flex-shrink-0">
        <div className="flex items-center space-x-1.5">
          <Camera className="w-3.5 h-3.5 text-[#082923]" />
          <h2 className="text-[11px] sm:text-xs font-black text-[#082923] tracking-wider uppercase font-mono">
            PRIMARY SURGICAL CAMERA • STEREO TRACKING
          </h2>
        </div>

        <div className="flex items-center space-x-1.5">
          {/* Live indicator badge */}
          <div className="flex items-center space-x-1 px-1.5 py-0.2 rounded-sm bg-[#3fa792] border border-[#26685c] text-[9px] font-mono font-bold text-[#082923]">
            <span className="w-1.5 h-1.5 rounded-full bg-[#084b3e] animate-ping" />
            <span>10Hz LIVE</span>
          </div>

          {/* Toggle Landmarks Overlay */}
          <button
            onClick={() => setShowOverlays(!showOverlays)}
            className={`px-1.5 py-0.5 rounded-sm border text-[9px] sm:text-[10px] flex items-center space-x-1 transition-all ${
              showOverlays 
                ? 'bg-[#3fa792] text-[#082923] border-[#26685c] font-bold shadow-sm' 
                : 'bg-[#c0eae1] text-[#1e584d] border-[#26685c] hover:bg-[#b0ded4]'
            }`}
            title="Toggle landmark overlay"
          >
            <Layers className="w-3 h-3" />
            <span className="font-mono">OVERLAY</span>
          </button>

          {/* Refresh Stream */}
          <button
            onClick={handleRefreshFeed}
            className="p-1 rounded-sm bg-[#c0eae1] hover:bg-[#b0ded4] text-[#082923] border border-[#26685c] transition-colors"
            title="Refresh Camera Feed"
          >
            <RefreshCw className="w-3 h-3" />
          </button>

          {/* Fullscreen Toggle */}
          <button
            onClick={toggleFullscreen}
            className="p-1 rounded-sm bg-[#c0eae1] hover:bg-[#b0ded4] text-[#082923] border border-[#26685c] transition-colors"
            title="Toggle Fullscreen"
          >
            {isFullscreen ? <Minimize2 className="w-3 h-3" /> : <Maximize2 className="w-3 h-3" />}
          </button>
        </div>
      </div>

      {/* Video / Stream Area */}
      <div className="relative flex-1 bg-[#07241f] flex items-center justify-center overflow-hidden min-h-0">
        {cameraStatus === 'ERROR' || streamError ? (
          <div className="flex flex-col items-center justify-center p-3 text-center space-y-1.5 bg-[#c0eae1] w-full h-full">
            <div className="w-8 h-8 rounded-sm bg-[#a8dcd1] border border-[#26685c] flex items-center justify-center text-[#26685c]">
              <AlertTriangle className="w-4 h-4" />
            </div>
            <div>
              <p className="text-xs font-black text-[#082923] font-mono">Live Stream Offline</p>
              <p className="text-[10px] text-[#20574b] mt-0.5">
                Check camera index 1 & PoseTracker pipeline.
              </p>
            </div>
            <button
              onClick={handleRefreshFeed}
              className="px-2.5 py-1 rounded-sm bg-[#53c0aa] hover:bg-[#3fa792] text-[#082923] text-[10px] font-mono font-bold border border-[#26685c]"
            >
              Retry Stream
            </button>
          </div>
        ) : (
          <img
            key={imgKey}
            src={`/api/camera/feed?t=${imgKey}`}
            alt="RoboSurge Live Camera Stream"
            onError={() => setStreamError(true)}
            className="w-full h-full object-cover select-none"
          />
        )}

        {/* HUD Overlay (Target Landmarks Chips on Top Left) */}
        {showOverlays && scene.landmarks && scene.landmarks.length > 0 && (
          <div className="absolute top-2 left-2 flex flex-wrap gap-1 pointer-events-auto max-w-[90%]">
            {scene.landmarks.map((lm) => (
              <button
                key={lm.name}
                onClick={() => onSelectLandmark && onSelectLandmark(lm.name)}
                className="group flex items-center space-x-1 px-1.5 py-0.5 rounded-sm bg-[#c0eae1]/95 backdrop-blur-md border border-[#26685c] text-[9px] sm:text-[10px] font-mono text-[#082923] shadow hover:bg-[#53c0aa] transition-all cursor-pointer"
              >
                <span className="w-1.5 h-1.5 rounded-full bg-[#108e68]" />
                <span className="font-extrabold">{lm.name.replace('landmark_', 'Tag ')}</span>
                <span className="text-[9px] text-[#20574b]">({lm.x.toFixed(1)}, {lm.y.toFixed(1)})</span>
                <span className="text-[8px] px-1 bg-[#3fa792] rounded-sm text-[#082923] font-black border border-[#26685c]">
                  {(lm.conf * 100).toFixed(0)}%
                </span>
              </button>
            ))}
          </div>
        )}

        {/* HUD Overlay Bottom Stats */}
        <div className="absolute bottom-1.5 right-1.5 flex items-center space-x-1.5 bg-[#c0eae1]/95 backdrop-blur-md px-1.5 py-0.5 rounded-sm border border-[#26685c] text-[8px] sm:text-[9px] font-mono text-[#082923] font-bold shadow-sm">
          <Focus className="w-2.5 h-2.5 text-[#108e68]" />
          <span>LocalAffine Homography Active</span>
        </div>
      </div>
    </div>
  );
};
