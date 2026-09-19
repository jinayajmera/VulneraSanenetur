import React from 'react';
import { Activity, CheckCircle2, Clock, Hash, MapPin, StopCircle } from 'lucide-react';
import { ExecutionStateData } from '../types/robosurge';

interface ExecutionCardProps {
  execution: ExecutionStateData;
  onAbort: () => void;
}

export const ExecutionCard: React.FC<ExecutionCardProps> = ({ execution, onAbort }) => {
  if (!execution.is_executing && !execution.last_results) {
    return null;
  }

  const results = execution.last_results;

  return (
    <div className="retro-panel p-2.5 flex flex-col space-y-2 animate-in fade-in duration-200 select-none flex-shrink-0">
      {/* Active Executing State */}
      {execution.is_executing && (
        <div className="flex items-center justify-between bg-[#53c0aa] border border-[#26685c] p-2 rounded-sm">
          <div className="flex items-center space-x-2">
            <div className="w-7 h-7 rounded-sm bg-[#3fa792] border border-[#26685c] flex items-center justify-center">
              <Activity className="w-3.5 h-3.5 text-[#082923] animate-spin" />
            </div>
            <div>
              <h4 className="text-xs font-extrabold text-[#082923] font-mono uppercase tracking-wide flex items-center space-x-1.5">
                <span>Robotic Procedure In Progress</span>
                <span className="w-1.5 h-1.5 rounded-full bg-[#084b3e] animate-ping" />
              </h4>
              <p className="text-[10px] text-[#15463c] font-sans">
                Streaming dynamic kinematics waypoints to ESP32 motion controller.
              </p>
            </div>
          </div>

          <button
            onClick={onAbort}
            className="px-3 py-1 bg-[#d84b4b] hover:bg-[#c93e3e] text-white font-bold text-xs font-mono tracking-wider rounded-sm border border-[#8a2222] flex items-center space-x-1 transition-all shadow-sm"
          >
            <StopCircle className="w-3.5 h-3.5" />
            <span>HALT MOTION</span>
          </button>
        </div>
      )}

      {/* Completed Results Report */}
      {!execution.is_executing && results && (
        <div className="space-y-1.5">
          <div className="flex items-center justify-between border-b border-[#26685c]/40 pb-1">
            <div className="flex items-center space-x-1.5 text-[#082923]">
              <CheckCircle2 className="w-3.5 h-3.5 text-[#108e68]" />
              <h3 className="text-xs font-bold uppercase font-mono tracking-wider">
                Execution Completed
              </h3>
            </div>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-1.5">
            {Object.entries(results).map(([key, res]) => (
              <div
                key={key}
                className="bg-[#b0ded4] p-2 rounded-sm border border-[#26685c] space-y-1 text-xs font-mono text-[#082923]"
              >
                <div className="flex items-center justify-between">
                  <span className="font-bold uppercase text-[11px]">Arm {res.arm_id}</span>
                  <span
                    className={`px-1.5 py-0.2 rounded-sm text-[9px] font-bold ${
                      res.aborted
                        ? 'bg-[#fecaca] text-[#991b1b] border border-[#dc2626]'
                        : 'bg-[#bbf7d0] text-[#166534] border border-[#16a34a]'
                    }`}
                  >
                    {res.status}
                  </span>
                </div>

                <div className="grid grid-cols-2 gap-1.5 text-[10px] text-[#20574b] pt-0.5">
                  <div className="flex items-center space-x-1">
                    <Clock className="w-3 h-3 text-[#26685c]" />
                    <span>Duration: {res.duration_s}s</span>
                  </div>
                  <div className="flex items-center space-x-1">
                    <Hash className="w-3 h-3 text-[#26685c]" />
                    <span>Steps: {res.steps_sent}</span>
                  </div>
                </div>

                <div className="flex items-center space-x-1 text-[9px] sm:text-[10px] text-[#082923] bg-[#c0eae1] p-1 rounded-sm border border-[#26685c]/60">
                  <MapPin className="w-3 h-3 text-[#108e68] flex-shrink-0" />
                  <span>
                    Final: ({res.final_position[0]}, {res.final_position[1]}, {res.final_position[2]}) cm
                  </span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
};
