import React, { useState, useEffect, useRef } from 'react';
import { 
  Heart, 
  Activity, 
  Compass, 
  Crosshair
} from 'lucide-react';
import { SceneStateData, ProcedurePlanData } from '../types/robosurge';

interface WorkspaceVisualizerProps {
  scene: SceneStateData;
  plan: ProcedurePlanData | null;
  onSelectLandmark?: (name: string) => void;
}

export const WorkspaceVisualizer: React.FC<WorkspaceVisualizerProps> = ({
  scene,
  onSelectLandmark,
}) => {
  const [hr, setHr] = useState(74);
  const [spo2, setSpo2] = useState(99);
  const [bpSys, setBpSys] = useState(120);
  const [bpDia, setBpDia] = useState(78);
  const [resp, setResp] = useState(16);
  const [temp, setTemp] = useState(36.8);

  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const interval = setInterval(() => {
      setHr(73 + Math.floor(Math.random() * 4));
      setSpo2(98 + (Math.random() > 0.3 ? 1 : 0));
      setBpSys(119 + Math.floor(Math.random() * 3));
      setBpDia(77 + Math.floor(Math.random() * 3));
      setResp(15 + Math.floor(Math.random() * 3));
      setTemp(36.7 + parseFloat((Math.random() * 0.2).toFixed(1)));
    }, 2400);
    return () => clearInterval(interval);
  }, []);

  // Smooth Live ECG Waveform Animation with Responsive Canvas
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    let animationFrameId: number;
    let x = 0;

    const updateDimensions = () => {
      if (!canvas) return;
      const rect = canvas.getBoundingClientRect();
      if (rect.width > 0 && rect.height > 0) {
        canvas.width = Math.floor(rect.width);
        canvas.height = Math.floor(rect.height);
      }
    };
    updateDimensions();
    window.addEventListener('resize', updateDimensions);

    let step = 0;
    const getEcgSample = (t: number, h: number) => {
      const scale = Math.max(0.6, h / 70);
      const cycle = t % 80;
      if (cycle >= 10 && cycle < 18) return -Math.sin(((cycle - 10) / 8) * Math.PI) * (6 * scale);
      if (cycle >= 24 && cycle < 27) return 3 * scale;
      if (cycle >= 27 && cycle < 33) return -24 * scale;
      if (cycle >= 33 && cycle < 37) return 8 * scale;
      if (cycle >= 44 && cycle < 58) return -Math.sin(((cycle - 44) / 14) * Math.PI) * (7 * scale);
      return 0;
    };

    let lastY = canvas.height / 2;

    const render = () => {
      const width = canvas.width || 400;
      const height = canvas.height || 60;
      const midY = height / 2;

      ctx.fillStyle = '#07241f';
      ctx.fillRect(x, 0, 8, height);

      ctx.strokeStyle = 'rgba(83, 192, 170, 0.12)';
      ctx.lineWidth = 1;
      for (let gy = 8; gy < height; gy += 14) {
        ctx.beginPath();
        ctx.moveTo(x, gy);
        ctx.lineTo(x + 8, gy);
        ctx.stroke();
      }

      const offset = getEcgSample(step, height);
      const currentY = midY + offset;

      ctx.strokeStyle = '#38e5b0';
      ctx.shadowColor = '#38e5b0';
      ctx.shadowBlur = 3;
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.moveTo(Math.max(0, x - 2), lastY);
      ctx.lineTo(x, currentY);
      ctx.stroke();

      lastY = currentY;
      x += 2;
      step += 1;

      if (x >= width) {
        x = 0;
        lastY = midY;
      }

      animationFrameId = requestAnimationFrame(render);
    };

    render();
    return () => {
      cancelAnimationFrame(animationFrameId);
      window.removeEventListener('resize', updateDimensions);
    };
  }, []);

  const arm1 = scene.arms.find((a) => a.id === 1);
  const arm2 = scene.arms.find((a) => a.id === 2);

  return (
    <div className="retro-panel overflow-hidden flex flex-col h-full min-h-0 select-none shadow-sm">
      
      {/* Panel Header */}
      <div className="retro-header flex items-center justify-between px-2.5 py-1 flex-shrink-0">
        <div className="flex items-center space-x-1.5">
          <Activity className="w-3.5 h-3.5 text-[#082923]" />
          <h2 className="text-[11px] sm:text-xs font-black text-[#082923] tracking-wider uppercase font-mono">
            CLINICAL TELEMETRY & PATIENT VITALS
          </h2>
        </div>
        <div className="flex items-center space-x-1 px-1.5 py-0.2 rounded-sm bg-[#3fa792] border border-[#26685c] text-[9px] font-mono font-bold text-[#082923]">
          <span className="w-1.5 h-1.5 rounded-full bg-[#084b3e] animate-ping" />
          <span>ALL NOMINAL</span>
        </div>
      </div>

      {/* Main Content Area - Fully utilizing vertical space */}
      <div className="p-1.5 flex-1 flex flex-col gap-1.5 overflow-hidden min-h-0">
        
        {/* 1. Patient Physiological Vitals (Flexing ECG Oscilloscope + Metrics) */}
        <div className="bg-[#b0ded4] rounded-sm p-1.5 border border-[#26685c] flex-1 flex flex-col gap-1 min-h-0">
          <div className="flex items-center justify-between text-[10px] sm:text-[11px] font-mono font-bold text-[#082923] flex-shrink-0">
            <span className="flex items-center space-x-1">
              <Heart className="w-3 h-3 text-[#d84b4b] fill-current animate-pulse" />
              <span>LEAD II ECG</span>
            </span>
            <span className="text-[9px] sm:text-[10px] text-[#108e68] font-bold">
              ● SINUS RHYTHM
            </span>
          </div>

          {/* Flexible Oscilloscope ECG Canvas */}
          <div className="relative rounded-sm border border-[#26685c] overflow-hidden bg-[#07241f] flex-1 min-h-[48px] flex items-center justify-center">
            <canvas ref={canvasRef} className="w-full h-full block" />
            <div className="absolute top-0.5 left-1.5 flex items-center space-x-1 text-[8px] sm:text-[9px] font-mono text-[#53c0aa] font-bold">
              <span>25 mm/s</span>
            </div>
            <div className="absolute top-0.5 right-1.5 flex items-center space-x-1 text-[10px] sm:text-[11px] font-mono text-[#38e5b0] font-black">
              <Heart className="w-2.5 h-2.5 text-[#d84b4b] fill-current" />
              <span>{hr} BPM</span>
            </div>
          </div>

          {/* Compact Vitals Readout Grid */}
          <div className="grid grid-cols-4 gap-1 text-center font-mono flex-shrink-0">
            <div className="bg-[#c0eae1] p-0.5 rounded-sm border border-[#26685c] text-[#082923]">
              <span className="text-[7px] sm:text-[8px] text-[#20574b] block font-bold">HR</span>
              <span className="text-[11px] sm:text-xs font-black text-[#082923]">{hr}</span>
            </div>

            <div className="bg-[#c0eae1] p-0.5 rounded-sm border border-[#26685c] text-[#082923]">
              <span className="text-[7px] sm:text-[8px] text-[#20574b] block font-bold">SpO2</span>
              <span className="text-[11px] sm:text-xs font-black text-[#108e68]">{spo2}%</span>
            </div>

            <div className="bg-[#c0eae1] p-0.5 rounded-sm border border-[#26685c] text-[#082923]">
              <span className="text-[7px] sm:text-[8px] text-[#20574b] block font-bold">NIBP</span>
              <span className="text-[11px] sm:text-xs font-black text-[#082923]">{bpSys}/{bpDia}</span>
            </div>

            <div className="bg-[#c0eae1] p-0.5 rounded-sm border border-[#26685c] text-[#082923]">
              <span className="text-[7px] sm:text-[8px] text-[#20574b] block font-bold">RESP/TEMP</span>
              <span className="text-[11px] sm:text-xs font-black text-[#082923]">{resp}/{temp}°</span>
            </div>
          </div>
        </div>

        {/* 2. Dual-Arm Spatial Pose */}
        <div className="bg-[#b0ded4] rounded-sm p-1.5 border border-[#26685c] space-y-1 flex-shrink-0">
          <div className="flex items-center justify-between text-[10px] font-mono font-bold text-[#082923]">
            <span className="flex items-center space-x-1">
              <Compass className="w-3 h-3 text-[#175245]" />
              <span>ARMS SPATIAL POSE</span>
            </span>
            <span className="text-[8px] sm:text-[9px] px-1 py-0.2 rounded-sm bg-[#c0eae1] border border-[#26685c]">
              Z-Offset: {scene.tool_offset.toFixed(1)} cm
            </span>
          </div>

          <div className="grid grid-cols-2 gap-1 text-[10px] sm:text-[11px] font-mono">
            <div className="bg-[#c0eae1] p-1 rounded-sm border border-[#26685c] text-[#082923]">
              <span className="text-[7px] sm:text-[8px] text-[#20574b] block font-bold">ARM 1 (SCALPEL)</span>
              <span className="font-extrabold text-[10px] sm:text-[11px] block text-[#082923]">
                {arm1 ? `(${arm1.x.toFixed(1)}, ${arm1.y.toFixed(1)}, ${arm1.z.toFixed(1)})` : 'OFFLINE'}
              </span>
            </div>

            <div className="bg-[#c0eae1] p-1 rounded-sm border border-[#26685c] text-[#082923]">
              <span className="text-[7px] sm:text-[8px] text-[#20574b] block font-bold">ARM 2 (RETRACTOR)</span>
              <span className="font-extrabold text-[10px] sm:text-[11px] block text-[#082923]">
                {arm2 ? `(${arm2.x.toFixed(1)}, ${arm2.y.toFixed(1)}, ${arm2.z.toFixed(1)})` : 'OFFLINE'}
              </span>
            </div>
          </div>
        </div>

        {/* 3. Anatomical Landmarks Target Anchors */}
        <div className="bg-[#b0ded4] rounded-sm p-1.5 border border-[#26685c] space-y-1 flex-shrink-0">
          <div className="flex items-center justify-between text-[10px] font-mono font-bold text-[#082923]">
            <span className="flex items-center space-x-1">
              <Crosshair className="w-3 h-3 text-[#175245]" />
              <span>ANATOMICAL ANCHORS ({scene.landmarks.length})</span>
            </span>
            <span className="text-[8px] sm:text-[9px] text-[#20574b]">Click to target</span>
          </div>

          <div className="flex flex-wrap gap-1">
            {scene.landmarks.length === 0 ? (
              <div className="w-full bg-[#c0eae1] py-0.5 px-1.5 rounded-sm border border-[#26685c] text-center text-[9px] sm:text-[10px] font-mono text-[#20574b] italic">
                Scanning camera field for markers...
              </div>
            ) : (
              scene.landmarks.map((lm) => {
                const confPercent = Math.round(lm.conf * 100);
                return (
                  <button
                    key={lm.name}
                    onClick={() => onSelectLandmark && onSelectLandmark(lm.name)}
                    className="px-1.5 py-0.5 rounded-sm bg-[#c0eae1] hover:bg-[#53c0aa] border border-[#26685c] text-[9px] sm:text-[10px] font-mono font-bold text-[#082923] transition-all flex items-center space-x-1"
                  >
                    <span className="w-1.5 h-1.5 rounded-full bg-[#108e68]" />
                    <span>{lm.name.replace('landmark_', 'Tag ')}</span>
                    <span className="text-[8px] sm:text-[9px] text-[#174e43]">({lm.x.toFixed(1)}, {lm.y.toFixed(1)})</span>
                    <span className="px-1 bg-[#3fa792] rounded-sm text-[7px] sm:text-[8px] text-[#082923] font-black">
                      {confPercent}%
                    </span>
                  </button>
                );
              })
            )}
          </div>
        </div>

      </div>
    </div>
  );
};
