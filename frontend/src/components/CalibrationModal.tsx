import React, { useState, useEffect } from 'react';
import { 
  Sliders, 
  X, 
  Move, 
  Maximize2, 
  RotateCcw, 
  Cpu, 
  Check, 
  AlertCircle 
} from 'lucide-react';
import { CalibrationData } from '../types/robosurge';
import { ApiService } from '../services/api';

interface CalibrationModalProps {
  isOpen: boolean;
  onClose: () => void;
  calibration: CalibrationData;
  onUpdate: () => void;
}

export const CalibrationModal: React.FC<CalibrationModalProps> = ({
  isOpen,
  onClose,
  calibration,
  onUpdate,
}) => {
  const [activeTab, setActiveTab] = useState<'robot' | 'tool'>('robot');

  // Robot calibration state
  const [nudgeX, setNudgeX] = useState('0.0');
  const [nudgeY, setNudgeY] = useState('0.0');
  const [scaleX, setScaleX] = useState(calibration.scale_x.toString());
  const [scaleY, setScaleY] = useState(calibration.scale_y.toString());

  // Tool Z calibration state
  const [baseAngle, setBaseAngle] = useState('90');
  const [shoulderAngle, setShoulderAngle] = useState('45');
  const [elbowAngle, setElbowAngle] = useState('45');
  const [directOffset, setDirectOffset] = useState(calibration.tool_z_offset_cm.toString());

  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState<{ text: string; isError?: boolean } | null>(null);

  useEffect(() => {
    setScaleX(calibration.scale_x.toString());
    setScaleY(calibration.scale_y.toString());
    setDirectOffset(calibration.tool_z_offset_cm.toString());
  }, [calibration]);

  if (!isOpen) return null;

  const handleNudge = async () => {
    setLoading(true);
    setMessage(null);
    try {
      const dx = parseFloat(nudgeX) || 0;
      const dy = parseFloat(nudgeY) || 0;
      await ApiService.nudge(dx, dy);
      setMessage({ text: `Nudged targets: dx=${dx > 0 ? `+${dx}` : dx}cm, dy=${dy > 0 ? `+${dy}` : dy}cm` });
      setNudgeX('0.0');
      setNudgeY('0.0');
      onUpdate();
    } catch (e: any) {
      setMessage({ text: e.message, isError: true });
    } finally {
      setLoading(false);
    }
  };

  const handleScale = async () => {
    setLoading(true);
    setMessage(null);
    try {
      const sx = parseFloat(scaleX) || 1.0;
      const sy = parseFloat(scaleY) || 1.0;
      await ApiService.scale(sx, sy);
      setMessage({ text: `Updated robot XY scale to sx=${sx}, sy=${sy}` });
      onUpdate();
    } catch (e: any) {
      setMessage({ text: e.message, isError: true });
    } finally {
      setLoading(false);
    }
  };

  const handleReset = async () => {
    setLoading(true);
    setMessage(null);
    try {
      await ApiService.resetCalibration();
      setMessage({ text: 'Reset robot calibration offsets to 0.0 and scale to 1.0' });
      onUpdate();
    } catch (e: any) {
      setMessage({ text: e.message, isError: true });
    } finally {
      setLoading(false);
    }
  };

  const handleDirectOffset = async () => {
    setLoading(true);
    setMessage(null);
    try {
      const off = parseFloat(directOffset) || 0.0;
      await ApiService.setToolOffset(off);
      setMessage({ text: `Tool Z-offset updated to ${off.toFixed(4)} cm` });
      onUpdate();
    } catch (e: any) {
      setMessage({ text: e.message, isError: true });
    } finally {
      setLoading(false);
    }
  };

  const handleCalculateFK = async () => {
    setLoading(true);
    setMessage(null);
    try {
      const b = parseFloat(baseAngle) || 0;
      const s = parseFloat(shoulderAngle) || 0;
      const e = parseFloat(elbowAngle) || 0;
      const res = await ApiService.calculateFK(b, s, e);
      setMessage({
        text: `Computed FK tip Z = ${res.tip_z} cm → Saved Tool Offset = ${res.tool_z_offset_cm} cm`,
      });
      setDirectOffset(res.tool_z_offset_cm.toString());
      onUpdate();
    } catch (err: any) {
      setMessage({ text: err.message, isError: true });
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm flex items-center justify-center p-4 select-none">
      <div className="bg-[#c0eae1] border-2 border-[#26685c] rounded-sm max-w-xl w-full p-4 shadow-2xl animate-in fade-in zoom-in-95 duration-150 space-y-3">
        
        {/* Modal Header */}
        <div className="flex items-center justify-between border-b border-[#26685c]/40 pb-2">
          <div className="flex items-center space-x-2 text-[#082923]">
            <Sliders className="w-4 h-4 text-[#1b5b4e]" />
            <h3 className="text-xs sm:text-sm font-extrabold uppercase font-mono tracking-wider">
              Robot & Tool Calibration
            </h3>
          </div>
          <button
            onClick={onClose}
            className="p-1 rounded-sm text-[#20574b] hover:text-[#082923] hover:bg-[#b0ded4] transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Tabs */}
        <div className="flex border-b border-[#26685c]/40 text-xs font-mono">
          <button
            onClick={() => { setActiveTab('robot'); setMessage(null); }}
            className={`pb-1.5 px-3 font-bold transition-colors border-b-2 ${
              activeTab === 'robot'
                ? 'border-[#26685c] text-[#082923]'
                : 'border-transparent text-[#20574b] hover:text-[#082923]'
            }`}
          >
            Robot XY Frame Calibration
          </button>
          <button
            onClick={() => { setActiveTab('tool'); setMessage(null); }}
            className={`pb-1.5 px-3 font-bold transition-colors border-b-2 ${
              activeTab === 'tool'
                ? 'border-[#26685c] text-[#082923]'
                : 'border-transparent text-[#20574b] hover:text-[#082923]'
            }`}
          >
            Tool Z-Offset & FK Calibration
          </button>
        </div>

        {/* Notification / Feedback Banner */}
        {message && (
          <div
            className={`p-2 rounded-sm text-xs font-mono flex items-center space-x-2 ${
              message.isError
                ? 'bg-[#fecaca] border border-[#dc2626] text-[#991b1b] font-bold'
                : 'bg-[#bbf7d0] border border-[#16a34a] text-[#166534] font-bold'
            }`}
          >
            {message.isError ? <AlertCircle className="w-4 h-4 flex-shrink-0" /> : <Check className="w-4 h-4 flex-shrink-0" />}
            <span>{message.text}</span>
          </div>
        )}

        {/* Tab 1: Robot Frame XY Calibration */}
        {activeTab === 'robot' && (
          <div className="space-y-3">
            {/* Current Values */}
            <div className="grid grid-cols-2 gap-2 bg-[#b0ded4] p-2 rounded-sm border border-[#26685c] text-xs font-mono text-[#082923]">
              <div>
                <span className="text-[#20574b] block text-[10px]">CURRENT XY OFFSET</span>
                <span className="font-bold">
                  ({calibration.offset_x_cm > 0 ? `+${calibration.offset_x_cm.toFixed(2)}` : calibration.offset_x_cm.toFixed(2)}, {calibration.offset_y_cm > 0 ? `+${calibration.offset_y_cm.toFixed(2)}` : calibration.offset_y_cm.toFixed(2)}) cm
                </span>
              </div>
              <div>
                <span className="text-[#20574b] block text-[10px]">CURRENT XY SCALE</span>
                <span className="font-bold">
                  ({calibration.scale_x.toFixed(3)}, {calibration.scale_y.toFixed(3)})
                </span>
              </div>
            </div>

            {/* Nudge Controls */}
            <div className="space-y-1">
              <label className="text-xs font-mono text-[#082923] flex items-center space-x-1.5 font-bold">
                <Move className="w-3.5 h-3.5 text-[#1b5b4e]" />
                <span>Nudge Targets (Add/Subtract cm Offset)</span>
              </label>
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <span className="text-[10px] font-mono text-[#20574b]">dx (cm)</span>
                  <input
                    type="number"
                    step="0.1"
                    value={nudgeX}
                    onChange={(e) => setNudgeX(e.target.value)}
                    className="w-full bg-[#d8f5ee] border border-[#26685c] rounded-sm p-1 text-xs font-mono text-[#082923] outline-none mt-0.5"
                  />
                </div>
                <div>
                  <span className="text-[10px] font-mono text-[#20574b]">dy (cm)</span>
                  <input
                    type="number"
                    step="0.1"
                    value={nudgeY}
                    onChange={(e) => setNudgeY(e.target.value)}
                    className="w-full bg-[#d8f5ee] border border-[#26685c] rounded-sm p-1 text-xs font-mono text-[#082923] outline-none mt-0.5"
                  />
                </div>
              </div>
              <button
                onClick={handleNudge}
                disabled={loading}
                className="w-full py-1 bg-[#53c0aa] hover:bg-[#3fa792] disabled:opacity-50 text-[#082923] font-bold text-xs font-mono rounded-sm border border-[#26685c] transition-colors"
              >
                Apply Nudge
              </button>
            </div>

            {/* Scale Controls */}
            <div className="space-y-1 pt-1.5 border-t border-[#26685c]/40">
              <label className="text-xs font-mono text-[#082923] flex items-center space-x-1.5 font-bold">
                <Maximize2 className="w-3.5 h-3.5 text-[#1b5b4e]" />
                <span>Scale Multipliers</span>
              </label>
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <span className="text-[10px] font-mono text-[#20574b]">Scale X</span>
                  <input
                    type="number"
                    step="0.05"
                    value={scaleX}
                    onChange={(e) => setScaleX(e.target.value)}
                    className="w-full bg-[#d8f5ee] border border-[#26685c] rounded-sm p-1 text-xs font-mono text-[#082923] outline-none mt-0.5"
                  />
                </div>
                <div>
                  <span className="text-[10px] font-mono text-[#20574b]">Scale Y</span>
                  <input
                    type="number"
                    step="0.05"
                    value={scaleY}
                    onChange={(e) => setScaleY(e.target.value)}
                    className="w-full bg-[#d8f5ee] border border-[#26685c] rounded-sm p-1 text-xs font-mono text-[#082923] outline-none mt-0.5"
                  />
                </div>
              </div>
              <button
                onClick={handleScale}
                disabled={loading}
                className="w-full py-1 bg-[#b0ded4] hover:bg-[#53c0aa] disabled:opacity-50 text-[#082923] font-bold text-xs font-mono rounded-sm border border-[#26685c] transition-colors"
              >
                Update Scale
              </button>
            </div>

            {/* Reset */}
            <div className="pt-1.5 border-t border-[#26685c]/40 flex justify-end">
              <button
                onClick={handleReset}
                disabled={loading}
                className="flex items-center space-x-1 px-2.5 py-1 rounded-sm bg-[#d84b4b] hover:bg-[#c93e3e] text-white text-xs font-mono font-bold border border-[#8a2222] transition-colors"
              >
                <RotateCcw className="w-3 h-3" />
                <span>Reset to Defaults</span>
              </button>
            </div>
          </div>
        )}

        {/* Tab 2: Tool Z-Offset & FK Calibration */}
        {activeTab === 'tool' && (
          <div className="space-y-3">
            <p className="text-xs text-[#15463c] leading-relaxed">
              Calibrate the tool tip height against the table surface. You can calculate the offset automatically from live joint angles via Forward Kinematics or set it directly.
            </p>

            {/* Interactive FK Calculator */}
            <div className="bg-[#b0ded4] p-2.5 rounded-sm border border-[#26685c] space-y-2">
              <h4 className="text-xs font-mono font-bold text-[#082923] uppercase flex items-center space-x-1.5">
                <Cpu className="w-3.5 h-3.5 text-[#1b5b4e]" />
                <span>Calculate via Forward Kinematics (FK)</span>
              </h4>
              <p className="text-[10px] text-[#20574b]">
                Manually jog Arm 1 until tip touches cardboard table surface, then enter servo angles:
              </p>

              <div className="grid grid-cols-3 gap-2 text-xs font-mono">
                <div>
                  <span className="text-[10px] text-[#20574b]">Base (°)</span>
                  <input
                    type="number"
                    value={baseAngle}
                    onChange={(e) => setBaseAngle(e.target.value)}
                    className="w-full bg-[#d8f5ee] border border-[#26685c] rounded-sm p-1 text-[#082923] outline-none mt-0.5"
                  />
                </div>
                <div>
                  <span className="text-[10px] text-[#20574b]">Shoulder (°)</span>
                  <input
                    type="number"
                    value={shoulderAngle}
                    onChange={(e) => setShoulderAngle(e.target.value)}
                    className="w-full bg-[#d8f5ee] border border-[#26685c] rounded-sm p-1 text-[#082923] outline-none mt-0.5"
                  />
                </div>
                <div>
                  <span className="text-[10px] text-[#20574b]">Elbow (°)</span>
                  <input
                    type="number"
                    value={elbowAngle}
                    onChange={(e) => setElbowAngle(e.target.value)}
                    className="w-full bg-[#d8f5ee] border border-[#26685c] rounded-sm p-1 text-[#082923] outline-none mt-0.5"
                  />
                </div>
              </div>

              <button
                onClick={handleCalculateFK}
                disabled={loading}
                className="w-full py-1.5 bg-[#53c0aa] hover:bg-[#3fa792] disabled:opacity-50 text-[#082923] font-bold text-xs font-mono rounded-sm border border-[#26685c] transition-all shadow-sm"
              >
                Compute FK & Save Tool Offset
              </button>
            </div>

            {/* Direct Tool Offset Setting */}
            <div className="space-y-1 pt-1.5 border-t border-[#26685c]/40">
              <label className="text-xs font-mono text-[#082923] font-bold block">
                Direct Tool Z Offset (cm)
              </label>
              <div className="flex space-x-2">
                <input
                  type="number"
                  step="0.01"
                  value={directOffset}
                  onChange={(e) => setDirectOffset(e.target.value)}
                  className="flex-1 bg-[#d8f5ee] border border-[#26685c] rounded-sm p-1 text-xs font-mono text-[#082923] outline-none"
                />
                <button
                  onClick={handleDirectOffset}
                  disabled={loading}
                  className="px-3.5 py-1 bg-[#53c0aa] hover:bg-[#3fa792] text-[#082923] font-bold text-xs font-mono rounded-sm border border-[#26685c] transition-colors"
                >
                  Save Offset
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
