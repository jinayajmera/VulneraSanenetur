import React, { useState, useRef, useEffect } from 'react';
import { Terminal, ArrowDown, Download, Trash2 } from 'lucide-react';
import { LogEntry } from '../types/robosurge';

interface ActivityLogProps {
  logs: LogEntry[];
  onClearLogs?: () => void;
}

export const ActivityLog: React.FC<ActivityLogProps> = ({ logs, onClearLogs }) => {
  const [filter, setFilter] = useState<string>('ALL');
  const [autoScroll, setAutoScroll] = useState(true);
  const logContainerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (autoScroll && logContainerRef.current) {
      logContainerRef.current.scrollTop = logContainerRef.current.scrollHeight;
    }
  }, [logs, autoScroll]);

  const filteredLogs = logs.filter((log) => {
    if (filter === 'ALL') return true;
    return log.tag.toUpperCase() === filter.toUpperCase();
  });

  const errorCount = logs.filter((l) => l.tag === 'ALERT' || l.tag === 'ERROR').length;

  const handleExport = () => {
    const text = logs.map((l) => `[${l.time}] [${l.tag}] ${l.message}`).join('\n');
    const blob = new Blob([text], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `robosurge_log_${Date.now()}.txt`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const getTagBadge = (tag: string) => {
    switch (tag.toUpperCase()) {
      case 'SYS':
        return 'bg-[#a3e2d3] text-[#085344] border-[#26685c] font-bold';
      case 'CMD':
        return 'bg-[#99d7eb] text-[#0c4e68] border-[#206980] font-bold';
      case 'ALERT':
      case 'ERROR':
        return 'bg-[#fecaca] text-[#991b1b] border-[#dc2626] font-bold';
      case 'WARN':
        return 'bg-[#fef3c7] text-[#92400e] border-[#d97706] font-bold';
      case 'EXEC':
        return 'bg-[#bbf7d0] text-[#166534] border-[#16a34a] font-bold';
      default:
        return 'bg-[#c0eae1] text-[#082923] border-[#26685c]';
    }
  };

  return (
    <div className="retro-panel overflow-hidden flex flex-col h-full min-h-0 p-2.5 select-none shadow-sm space-y-1.5">
      {/* Log Header */}
      <div className="flex flex-wrap items-center justify-between gap-1.5 pb-1.5 border-b border-[#26685c]/40 flex-shrink-0">
        <div className="flex items-center space-x-2">
          <Terminal className="w-3.5 h-3.5 text-[#082923]" />
          <h2 className="text-xs font-black text-[#082923] tracking-wider uppercase font-mono">
            ACTIVITY AUDIT LOG
          </h2>
          <span className="text-[9px] font-mono px-1.5 py-0.2 rounded-sm bg-[#b0ded4] border border-[#26685c] text-[#082923]">
            {logs.length} events {errorCount > 0 ? `• ${errorCount} alerts` : ''}
          </span>
        </div>

        {/* Action buttons on right */}
        <div className="flex items-center space-x-1 text-[11px] font-mono">
          {onClearLogs && (
            <button
              onClick={onClearLogs}
              className="px-2 py-0.5 rounded-sm bg-[#b0ded4] hover:bg-[#53c0aa] border border-[#26685c] text-[#082923] font-bold transition-colors flex items-center space-x-1"
              title="Clear log"
            >
              <Trash2 className="w-3 h-3" />
              <span>CLEAR</span>
            </button>
          )}

          <button
            onClick={handleExport}
            className="px-2 py-0.5 rounded-sm bg-[#b0ded4] hover:bg-[#53c0aa] border border-[#26685c] text-[#082923] font-bold transition-colors flex items-center space-x-1"
            title="Export log as text file"
          >
            <Download className="w-3 h-3" />
            <span>EXPORT</span>
          </button>

          {/* Auto-scroll button */}
          <button
            onClick={() => setAutoScroll(!autoScroll)}
            className={`p-1 rounded-sm border border-[#26685c] transition-colors ${
              autoScroll ? 'text-[#082923] bg-[#53c0aa] font-bold' : 'text-[#20574b] bg-[#b0ded4]'
            }`}
            title={autoScroll ? 'Auto-scroll enabled' : 'Auto-scroll paused'}
          >
            <ArrowDown className="w-3 h-3" />
          </button>
        </div>
      </div>

      {/* Filter Chips */}
      <div className="flex items-center space-x-1 text-[10px] font-mono pt-0.5 flex-shrink-0">
        {['ALL', 'SYS', 'CMD', 'ALERT', 'EXEC'].map((f) => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            className={`px-2 py-0.2 rounded-sm transition-all border ${
              filter === f
                ? 'bg-[#53c0aa] text-[#082923] border-[#26685c] font-black shadow-sm'
                : 'bg-[#b0ded4] text-[#20574b] border-transparent hover:text-[#082923] hover:border-[#26685c]'
            }`}
          >
            {f}
          </button>
        ))}
      </div>

      {/* Log Feed */}
      <div
        ref={logContainerRef}
        className="flex-1 min-h-0 overflow-y-auto space-y-1 font-mono text-[11px] text-[#082923] pr-1 mt-1"
      >
        {filteredLogs.length === 0 ? (
          <div className="text-[#20574b] italic py-6 text-center text-[11px]">
            No telemetry events logged yet.
          </div>
        ) : (
          filteredLogs.map((log, idx) => (
            <div
              key={`log-${idx}`}
              className="flex items-start space-x-1.5 py-0.5 px-1.5 rounded-sm bg-[#b0ded4]/40 hover:bg-[#b0ded4] transition-colors border border-transparent hover:border-[#26685c]/30"
            >
              <span className="text-[9px] text-[#20574b] flex-shrink-0 pt-0.2 px-1 py-0.2 bg-[#c0eae1] rounded-sm border border-[#26685c]/40 font-mono font-bold">
                {log.time}
              </span>
              <span
                className={`text-[8px] px-1 py-0.2 rounded-sm border font-mono flex-shrink-0 font-bold ${getTagBadge(
                  log.tag
                )}`}
              >
                {log.tag}
              </span>
              <span className="text-[#082923] text-[11px] break-all leading-tight font-sans font-medium">
                {log.message}
              </span>
            </div>
          ))
        )}
      </div>
    </div>
  );
};
