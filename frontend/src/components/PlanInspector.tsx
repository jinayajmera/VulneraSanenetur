import React, { useState, useEffect } from 'react';
import { 
  AlertCircle, 
  Clock, 
  ShieldCheck, 
  Terminal, 
  Play, 
  Copy, 
  Check, 
  Sparkles,
  GitBranch,
  Edit3,
  X,
  RotateCcw,
  CheckCircle2,
  Mic
} from 'lucide-react';
import { PlanningStateData } from '../types/robosurge';
import { ApiService } from '../services/api';

interface PlanInspectorProps {
  planning: PlanningStateData;
  isExecuting: boolean;
  onExecuteSuccess: () => void;
}

export const PlanInspector: React.FC<PlanInspectorProps> = ({
  planning,
  isExecuting,
  onExecuteSuccess,
}) => {
  const [activeTab, setActiveTab] = useState<'waypoints' | 'serial'>('waypoints');
  const [copied, setCopied] = useState(false);
  const [showConfirmModal, setShowConfirmModal] = useState(false);
  const [executingLocal, setExecutingLocal] = useState(false);

  // Doctor Brief Editing State
  const [isEditingBrief, setIsEditingBrief] = useState(false);
  const [editedBrief, setEditedBrief] = useState('');
  const [updatingBrief, setUpdatingBrief] = useState(false);
  const [briefError, setBriefError] = useState<string | null>(null);
  const [isDictatingBrief, setIsDictatingBrief] = useState(false);

  const plan = planning.plan;
  const validation = planning.validation;

  // Sync editedBrief text whenever the plan/translation changes if not currently editing
  useEffect(() => {
    if (!isEditingBrief) {
      setEditedBrief(planning.nl_translation || plan?.rationale || '');
    }
  }, [planning.nl_translation, plan?.rationale, isEditingBrief]);

  if (!plan) {
    return (
      <div className="retro-panel p-4 flex flex-col items-center justify-center text-center h-full min-h-0 space-y-2 select-none shadow-sm">
        <div className="w-9 h-9 rounded-sm bg-[#b0ded4] border border-[#26685c] flex items-center justify-center text-[#26685c] shadow-inner">
          <Terminal className="w-5 h-5" />
        </div>
        <div>
          <h3 className="text-xs font-extrabold text-[#082923] uppercase font-mono">
            No Active Surgical Plan
          </h3>
          <p className="text-[11px] text-[#20574b] max-w-md font-mono mt-0.5 leading-tight">
            Transmit a command in the console above or select a Quick Protocol to generate synchronized dual-arm waypoints with safety bounds validation.
          </p>
        </div>
      </div>
    );
  }

  const handleCopySerial = () => {
    if (!planning.serial_preview) return;
    navigator.clipboard.writeText(planning.serial_preview.join('\n'));
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleStartEdit = () => {
    setEditedBrief(planning.nl_translation || plan.rationale || '');
    setBriefError(null);
    setIsEditingBrief(true);
  };

  const handleCancelEdit = () => {
    setEditedBrief(planning.nl_translation || plan.rationale || '');
    setBriefError(null);
    setIsEditingBrief(false);
    setIsDictatingBrief(false);
  };

  const toggleBriefMic = () => {
    if (!('webkitSpeechRecognition' in window || 'SpeechRecognition' in window)) {
      alert('Speech recognition is not supported in this browser. Please use Chrome, Edge, or a WebSpeech-enabled browser.');
      return;
    }

    try {
      const SpeechRecognition = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;

      if (isDictatingBrief) {
        setIsDictatingBrief(false);
        return;
      }

      const recognition = new SpeechRecognition();
      recognition.continuous = true;
      recognition.interimResults = true;
      recognition.lang = 'en-US';

      recognition.onstart = () => setIsDictatingBrief(true);
      recognition.onend = () => setIsDictatingBrief(false);
      recognition.onerror = () => setIsDictatingBrief(false);

      const baseText = editedBrief ? `${editedBrief.trim()} ` : '';
      recognition.onresult = (event: any) => {
        let transcript = '';
        for (let i = 0; i < event.results.length; ++i) {
          transcript += event.results[i][0].transcript;
        }
        setEditedBrief(`${baseText}${transcript}`.trim());
      };

      recognition.start();
    } catch {
      setIsDictatingBrief(false);
    }
  };

  const handleSaveBrief = async () => {
    if (!editedBrief.trim()) {
      setBriefError('Brief text cannot be empty');
      return;
    }
    setUpdatingBrief(true);
    setBriefError(null);
    setIsDictatingBrief(false);
    try {
      await ApiService.updateBrief(editedBrief);
      setIsEditingBrief(false);
      onExecuteSuccess(); // Trigger status refresh to update waypoints table and 3D visualizer
    } catch (e: any) {
      setBriefError(e.message || 'Failed to re-plan from edited brief');
    } finally {
      setUpdatingBrief(false);
    }
  };

  const handleExecute = async () => {
    setExecutingLocal(true);
    try {
      await ApiService.executePlan();
      setShowConfirmModal(false);
      onExecuteSuccess();
    } catch (e: any) {
      alert(`Execution failed: ${e.message}`);
    } finally {
      setExecutingLocal(false);
    }
  };

  const isValidationOk = validation ? validation.ok : true;

  return (
    <div className="retro-panel overflow-hidden flex flex-col h-full min-h-0 p-2.5 select-none shadow-sm space-y-2">
      {/* Top Header Card */}
      <div className="flex flex-wrap items-center justify-between gap-1.5 pb-1.5 border-b border-[#26685c]/40 flex-shrink-0">
        <div className="flex items-center space-x-2">
          <div className="px-2 py-0.5 rounded-sm bg-[#53c0aa] border border-[#26685c] text-[#082923] text-[10px] sm:text-[11px] font-mono font-black uppercase tracking-wider flex items-center space-x-1 shadow-sm">
            <span className="w-1.5 h-1.5 rounded-full bg-[#084b3e] animate-ping" />
            <span>{plan.procedure.toUpperCase()}</span>
          </div>
          <div className="flex items-center space-x-1 text-[10px] sm:text-[11px] text-[#20574b] font-mono font-bold">
            <Clock className="w-3 h-3" />
            <span>EST: ~{plan.duration.toFixed(1)}s</span>
          </div>
        </div>

        {/* Validation Status Badge & Execute Button */}
        <div className="flex items-center space-x-1.5">
          {isValidationOk ? (
            <div className="flex items-center space-x-1 px-2 py-0.5 rounded-sm bg-[#3fa792] text-[#082923] border border-[#26685c] text-[10px] font-mono font-extrabold shadow-sm">
              <ShieldCheck className="w-3 h-3" />
              <span>SAFETY PASSED</span>
            </div>
          ) : (
            <div className="flex items-center space-x-1 px-2 py-0.5 rounded-sm bg-[#d84b4b] text-white border border-[#8a2222] text-[10px] font-mono font-bold shadow-sm">
              <AlertCircle className="w-3 h-3" />
              <span>VALIDATION BLOCKED</span>
            </div>
          )}

          <button
            onClick={() => setShowConfirmModal(true)}
            disabled={!isValidationOk || isExecuting}
            className="px-3.5 py-0.5 bg-[#53c0aa] hover:bg-[#3fa792] active:scale-95 disabled:opacity-40 disabled:cursor-not-allowed text-[#082923] font-black text-[10px] sm:text-[11px] font-mono tracking-wider rounded-sm border border-[#26685c] flex items-center space-x-1 transition-all shadow-sm"
          >
            <Play className="w-3 h-3 fill-current" />
            <span>{isExecuting ? 'EXECUTING...' : 'EXECUTE PLAN'}</span>
          </button>
        </div>
      </div>

      {/* AI NL Translation & Clinical Rationale Box (with Direct Doctor Brief Editing) */}
      <div className="bg-[#b0ded4] rounded-sm p-2 border border-[#26685c] space-y-1.5 shadow-sm flex-shrink-0">
        <div className="flex items-center justify-between text-[11px]">
          <div className="flex items-center space-x-1.5 text-[#082923] font-mono font-bold">
            <Sparkles className="w-3.5 h-3.5 text-[#1b5b4e]" />
            <span className="text-[10px] sm:text-[11px]">Surgeon Briefing & AI Rationale:</span>
          </div>

          <div className="flex items-center space-x-1.5">
            {planning.is_doctor_edited && (
              <span className="px-1.5 py-0.2 rounded-xs bg-[#0c5949] text-[#e0f5f0] text-[9px] font-mono font-black tracking-wider flex items-center space-x-1">
                <CheckCircle2 className="w-2.5 h-2.5" />
                <span>DOCTOR MODIFIED</span>
              </span>
            )}

            {!isEditingBrief && (
              <button
                onClick={handleStartEdit}
                className="px-2 py-0.5 bg-[#c0eae1] hover:bg-[#a0dcce] active:scale-95 text-[#082923] text-[9px] sm:text-[10px] font-mono font-bold rounded-sm border border-[#26685c]/60 flex items-center space-x-1 transition-all shadow-xs"
                title="Directly edit the surgeon brief to regenerate safe waypoints"
              >
                <Edit3 className="w-3 h-3" />
                <span>Edit Brief</span>
              </button>
            )}
          </div>
        </div>

        {isEditingBrief ? (
          <div className="space-y-1.5 animate-in fade-in duration-100">
            <textarea
              value={editedBrief}
              onChange={(e) => setEditedBrief(e.target.value)}
              disabled={updatingBrief}
              rows={3}
              placeholder="Modify clinical parameters, cutting depth, speeds, landmarks, or closure patterns..."
              className="w-full text-[10px] sm:text-[11px] font-mono bg-[#d5f0ea] border-2 border-[#1b5b4e] rounded-sm p-1.5 text-[#082923] focus:outline-none focus:ring-1 focus:ring-[#1b5b4e] placeholder-[#4f8379] resize-none leading-relaxed"
            />

            {briefError && (
              <div className="text-[9px] font-mono p-1 bg-[#fecaca] border border-[#dc2626] rounded-sm text-[#991b1b] flex items-center space-x-1">
                <AlertCircle className="w-3 h-3 flex-shrink-0" />
                <span>{briefError}</span>
              </div>
            )}

            <div className="flex items-center justify-between pt-0.5">
              <button
                type="button"
                onClick={toggleBriefMic}
                disabled={updatingBrief}
                className={`px-2 py-0.5 text-[9px] sm:text-[10px] font-mono font-bold rounded-sm border border-[#26685c] flex items-center space-x-1 shadow-xs transition-all ${
                  isDictatingBrief
                    ? 'bg-[#dc2626] text-white animate-pulse'
                    : 'bg-[#b0ded4] hover:bg-[#97cfc3] text-[#082923]'
                }`}
                title={isDictatingBrief ? "Stop voice dictation" : "Voice Dictation (Speech-to-Text)"}
              >
                <Mic className="w-3 h-3" />
                <span>{isDictatingBrief ? 'Dictating (Recording...)' : 'Voice Dictate'}</span>
              </button>

              <div className="flex items-center space-x-1.5">
                <button
                  type="button"
                  onClick={handleCancelEdit}
                  disabled={updatingBrief}
                  className="px-2 py-0.5 text-[9px] sm:text-[10px] font-mono font-bold text-[#15463c] bg-[#a8dcd1] hover:bg-[#97cfc3] rounded-sm border border-[#26685c] flex items-center space-x-1 transition-colors"
                >
                  <X className="w-2.5 h-2.5" />
                  <span>Cancel</span>
                </button>

                <button
                  type="button"
                  onClick={handleSaveBrief}
                  disabled={updatingBrief || !editedBrief.trim()}
                  className="px-2.5 py-0.5 text-[9px] sm:text-[10px] font-mono font-black text-[#082923] bg-[#53c0aa] hover:bg-[#3fa792] active:scale-95 disabled:opacity-50 disabled:cursor-not-allowed rounded-sm border border-[#26685c] flex items-center space-x-1 shadow-sm transition-all"
                >
                  {updatingBrief ? (
                    <>
                      <RotateCcw className="w-3 h-3 animate-spin" />
                      <span>Re-calculating Waypoints...</span>
                    </>
                  ) : (
                    <>
                      <Sparkles className="w-3 h-3 fill-current" />
                      <span>Regenerate Waypoints from Brief</span>
                    </>
                  )}
                </button>
              </div>
            </div>
          </div>
        ) : (
          <p className="text-[10px] sm:text-[11px] text-[#15463c] leading-tight font-sans font-medium">
            {planning.nl_translation || plan.rationale}
          </p>
        )}

        {plan.safety_notes && !isEditingBrief && (
          <p className="text-[9px] sm:text-[10px] text-[#7a4e0a] font-mono bg-[#fef3c7] px-1.5 py-0.5 rounded-sm border border-[#f59e0b]/40 font-bold">
            Safety: {plan.safety_notes}
          </p>
        )}
      </div>

      {/* Validation Diagnostic List */}
      {validation && (validation.errors.length > 0 || validation.warnings.length > 0) && (
        <div className="space-y-1 flex-shrink-0">
          {validation.errors.map((err, idx) => (
            <div key={`err-${idx}`} className="text-[10px] font-mono p-1 bg-[#fecaca] border border-[#dc2626] rounded-sm text-[#991b1b] flex items-center space-x-1.5 font-bold">
              <AlertCircle className="w-3.5 h-3.5 flex-shrink-0" />
              <span>ERROR: {err}</span>
            </div>
          ))}
          {validation.warnings.map((warn, idx) => (
            <div key={`warn-${idx}`} className="text-[10px] font-mono p-1 bg-[#fef3c7] border border-[#d97706] rounded-sm text-[#92400e] flex items-center space-x-1.5">
              <AlertCircle className="w-3.5 h-3.5 flex-shrink-0" />
              <span>WARN: {warn}</span>
            </div>
          ))}
        </div>
      )}

      {/* Tabs for Detailed Inspection */}
      <div className="flex-1 flex flex-col min-h-0 space-y-1.5">
        <div className="flex items-center justify-between border-b border-[#26685c]/40 text-[10px] sm:text-[11px] font-mono flex-shrink-0">
          <div className="flex space-x-3">
            <button
              onClick={() => setActiveTab('waypoints')}
              className={`pb-1 font-extrabold transition-colors border-b-2 flex items-center space-x-1 ${
                activeTab === 'waypoints'
                  ? 'border-[#26685c] text-[#082923]'
                  : 'border-transparent text-[#20574b] hover:text-[#082923]'
              }`}
            >
              <GitBranch className="w-3 h-3" />
              <span>Waypoints ({plan.arm1.waypoints.length + plan.arm2.waypoints.length})</span>
            </button>
            <button
              onClick={() => setActiveTab('serial')}
              className={`pb-1 font-extrabold transition-colors border-b-2 flex items-center space-x-1 ${
                activeTab === 'serial'
                  ? 'border-[#26685c] text-[#082923]'
                  : 'border-transparent text-[#20574b] hover:text-[#082923]'
              }`}
            >
              <Terminal className="w-3 h-3" />
              <span>Serial G-Code Preview</span>
            </button>
          </div>

          {activeTab === 'serial' && (
            <button
              onClick={handleCopySerial}
              className="flex items-center space-x-1 text-[10px] text-[#082923] hover:text-[#26685c] pb-1 font-bold"
            >
              {copied ? <Check className="w-3 h-3 text-[#108e68]" /> : <Copy className="w-3 h-3 text-[#20574b]" />}
              <span>{copied ? 'Copied' : 'Copy'}</span>
            </button>
          )}
        </div>

        {/* Tab 1: Waypoints Table */}
        {activeTab === 'waypoints' && (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-2 flex-1 min-h-0 overflow-y-auto pr-1">
            {/* Arm 1 */}
            <div className="bg-[#b0ded4] p-2 rounded-sm border border-[#26685c] space-y-1">
              <div className="flex items-center justify-between text-[10px] sm:text-[11px] font-mono font-extrabold text-[#082923]">
                <span>Arm 1 ({plan.arm1.role})</span>
                <span className="text-[9px] px-1 py-0.2 rounded-sm bg-[#c0eae1] border border-[#26685c]">
                  {plan.arm1.feed} mm/s
                </span>
              </div>
              <div className="space-y-0.5">
                {plan.arm1.waypoints.map((wp, idx) => (
                  <div key={`a1-${idx}`} className="flex items-center justify-between text-[10px] font-mono bg-[#c0eae1] px-2 py-0.5 rounded-sm border border-[#26685c]/60 text-[#082923]">
                    <span className="font-bold">[{wp.label}]</span>
                    <span>
                      ({wp.x > 0 ? `+${wp.x.toFixed(2)}` : wp.x.toFixed(2)}, {wp.y > 0 ? `+${wp.y.toFixed(2)}` : wp.y.toFixed(2)}, {wp.z.toFixed(2)}) cm
                    </span>
                  </div>
                ))}
              </div>
            </div>

            {/* Arm 2 */}
            <div className="bg-[#b0ded4] p-2 rounded-sm border border-[#26685c] space-y-1">
              <div className="flex items-center justify-between text-[10px] sm:text-[11px] font-mono font-extrabold text-[#082923]">
                <span>Arm 2 ({plan.arm2.role})</span>
                <span className="text-[9px] px-1 py-0.2 rounded-sm bg-[#c0eae1] border border-[#26685c]">
                  {plan.arm2.feed} mm/s
                </span>
              </div>
              <div className="space-y-0.5">
                {plan.arm2.waypoints.map((wp, idx) => (
                  <div key={`a2-${idx}`} className="flex items-center justify-between text-[10px] font-mono bg-[#c0eae1] px-2 py-0.5 rounded-sm border border-[#26685c]/60 text-[#082923]">
                    <span className="font-bold">[{wp.label}]</span>
                    <span>
                      ({wp.x > 0 ? `+${wp.x.toFixed(2)}` : wp.x.toFixed(2)}, {wp.y > 0 ? `+${wp.y.toFixed(2)}` : wp.y.toFixed(2)}, {wp.z.toFixed(2)}) cm
                    </span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}

        {/* Tab 2: Serial Preview */}
        {activeTab === 'serial' && (
          <div className="bg-[#07241f] p-2.5 rounded-sm border border-[#26685c] font-mono text-[11px] text-[#a8dcd1] flex-1 min-h-0 overflow-y-auto space-y-0.5">
            {planning.serial_preview && planning.serial_preview.length > 0 ? (
              planning.serial_preview.map((cmd, idx) => (
                <div key={`ser-${idx}`} className="hover:text-white transition-colors">
                  {cmd}
                </div>
              ))
            ) : (
              <span className="text-[#3b7569]">No serial commands generated.</span>
            )}
          </div>
        )}
      </div>

      {/* Execution Confirmation Modal */}
      {showConfirmModal && (
        <div className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-[#c0eae1] border-2 border-[#26685c] rounded-sm max-w-lg w-full p-5 shadow-2xl animate-in fade-in zoom-in-95 duration-150 space-y-3">
            <div className="flex items-center space-x-2 text-[#082923]">
              <ShieldCheck className="w-6 h-6 text-[#108e68]" />
              <h3 className="text-sm font-black uppercase tracking-wider font-mono">
                Verify Procedure Execution
              </h3>
            </div>

            <div className="bg-[#b0ded4] p-3 rounded-sm border border-[#26685c] space-y-1 text-xs font-mono text-[#082923]">
              <div className="flex justify-between">
                <span className="text-[#20574b]">Procedure:</span>
                <span className="font-black">{plan.procedure.toUpperCase()}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-[#20574b]">Arm 1 (Cutting):</span>
                <span>{plan.arm1.waypoints.length} waypoints @ {plan.arm1.feed} mm/s</span>
              </div>
              <div className="flex justify-between">
                <span className="text-[#20574b]">Arm 2 (Retracting):</span>
                <span>{plan.arm2.waypoints.length} waypoints @ {plan.arm2.feed} mm/s</span>
              </div>
              <div className="flex justify-between">
                <span className="text-[#20574b]">Duration:</span>
                <span className="font-black">~{plan.duration.toFixed(1)}s</span>
              </div>
            </div>

            <p className="text-xs text-[#15463c] leading-relaxed">
              RoboSurge will stream validated waypoints to the ESP32 motion controller over serial.
            </p>

            <div className="flex items-center justify-end space-x-2 pt-1">
              <button
                onClick={() => setShowConfirmModal(false)}
                className="px-3.5 py-1.5 rounded-sm text-xs font-bold text-[#15463c] bg-[#a8dcd1] hover:bg-[#97cfc3] border border-[#26685c] transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={handleExecute}
                disabled={executingLocal}
                className="px-4 py-1.5 rounded-sm text-xs font-black text-[#082923] bg-[#53c0aa] hover:bg-[#3fa792] border border-[#26685c] transition-all flex items-center space-x-1.5 shadow-sm"
              >
                <Play className="w-3.5 h-3.5 fill-current" />
                <span>{executingLocal ? 'Starting...' : 'Confirm & Execute'}</span>
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
