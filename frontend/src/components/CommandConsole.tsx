import React, { useState } from 'react';
import { 
  Send, 
  Mic, 
  Scissors, 
  Zap, 
  Flame, 
  Brush, 
  GitCommit, 
  Home, 
  RefreshCw,
  Terminal,
  Crosshair
} from 'lucide-react';

interface CommandConsoleProps {
  onCommandSubmit: (cmd: string) => Promise<void>;
  isPlanning: boolean;
  selectedLandmark: string;
}

export const CommandConsole: React.FC<CommandConsoleProps> = ({
  onCommandSubmit,
  isPlanning,
  selectedLandmark,
}) => {
  const [command, setCommand] = useState('');
  const [isListening, setIsListening] = useState(false);

  const targetName = selectedLandmark ? selectedLandmark.replace('landmark_', 'landmark ') : 'landmark A';

  const presets = [
    {
      label: '3mm Incision',
      cmd: `make a 3mm incision at ${targetName}`,
      icon: Scissors,
    },
    {
      label: '5mm Biopsy',
      cmd: `perform biopsy at ${targetName}`,
      icon: Zap,
    },
    {
      label: 'Cauterize',
      cmd: `cauterize tissue at ${targetName}`,
      icon: Flame,
    },
    {
      label: 'Debridement',
      cmd: `debride tissue at ${targetName}`,
      icon: Brush,
    },
    {
      label: 'Suture 3 Stitches',
      cmd: `suture 3 stitches at ${targetName}`,
      icon: GitCommit,
    },
    {
      label: 'Go Home',
      cmd: 'go home',
      icon: Home,
    },
  ];

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!command.trim() || isPlanning) return;
    onCommandSubmit(command);
  };

  const handlePresetClick = (presetCmd: string) => {
    setCommand(presetCmd);
    onCommandSubmit(presetCmd);
  };

  const toggleMic = () => {
    if (!('webkitSpeechRecognition' in window || 'SpeechRecognition' in window)) {
      alert('Speech recognition is not supported in this browser. Please use Chrome, Edge, or a WebSpeech-enabled browser.');
      return;
    }

    try {
      const SpeechRecognition = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
      
      if (isListening) {
        setIsListening(false);
        return;
      }

      const recognition = new SpeechRecognition();
      recognition.continuous = false;
      recognition.interimResults = true;
      recognition.lang = 'en-US';

      recognition.onstart = () => setIsListening(true);
      recognition.onend = () => setIsListening(false);
      recognition.onerror = () => setIsListening(false);
      recognition.onresult = (event: any) => {
        let interimTranscript = '';
        let finalTranscript = '';
        for (let i = event.resultIndex; i < event.results.length; ++i) {
          if (event.results[i].isFinal) {
            finalTranscript += event.results[i][0].transcript;
          } else {
            interimTranscript += event.results[i][0].transcript;
          }
        }
        const currentText = finalTranscript || interimTranscript;
        if (currentText) {
          setCommand(currentText);
        }
        if (finalTranscript) {
          onCommandSubmit(finalTranscript);
        }
      };

      recognition.start();
    } catch {
      setIsListening(false);
    }
  };

  return (
    <div className="retro-panel overflow-hidden flex flex-col space-y-1.5 p-2 select-none shadow-sm flex-shrink-0">
      {/* Input + Target + Action row */}
      <form onSubmit={handleSubmit} className="flex items-center space-x-1.5">
        <div className="flex items-center space-x-1 px-2 py-1 rounded-sm bg-[#53c0aa] border border-[#26685c] text-[#082923] text-[10px] font-mono font-black flex-shrink-0">
          <Terminal className="w-3 h-3" />
          <span>CMD</span>
        </div>

        <div className="relative flex-1">
          <span className="absolute left-2.5 top-1.5 text-[#20574b] font-mono font-bold text-xs pointer-events-none">
            &gt;
          </span>
          <input
            type="text"
            value={command}
            onChange={(e) => setCommand(e.target.value)}
            placeholder={isListening ? "Listening... speak surgical command now" : `Enter surgical command... (target: ${targetName})`}
            disabled={isPlanning}
            className={`w-full border rounded-sm py-1 pl-6 pr-2 text-xs font-mono outline-none shadow-inner transition-colors ${
              isListening 
                ? 'bg-[#ffe4e4] border-[#dc2626] text-[#991b1b] placeholder-[#b91c1c] animate-pulse' 
                : 'bg-[#d8f5ee] border-[#26685c] text-[#082923] placeholder-[#3b7569] focus:bg-[#e9fbf6] focus:border-[#12453c]'
            }`}
          />
        </div>

        {/* Target Anchor indicator */}
        <div className="hidden sm:flex items-center space-x-1 px-2 py-1 rounded-sm bg-[#b0ded4] border border-[#26685c] text-[10px] font-mono text-[#082923] flex-shrink-0">
          <Crosshair className="w-3 h-3 text-[#175245]" />
          <span className="font-bold">{targetName}</span>
        </div>

        {/* Send Button */}
        <button
          type="submit"
          disabled={!command.trim() || isPlanning}
          className="px-3 py-1 bg-[#53c0aa] hover:bg-[#3fa792] active:scale-95 disabled:opacity-50 text-[#082923] font-black text-xs font-mono tracking-wider rounded-sm flex items-center space-x-1 border border-[#26685c] shadow-sm transition-all flex-shrink-0"
        >
          {isPlanning ? (
            <>
              <RefreshCw className="w-3 h-3 animate-spin" />
              <span>PLANNING...</span>
            </>
          ) : (
            <>
              <Send className="w-3 h-3" />
              <span>TRANSMIT</span>
            </>
          )}
        </button>

        {/* Voice Input Button */}
        <button
          type="button"
          onClick={toggleMic}
          className={`p-1 rounded-sm border border-[#26685c] shadow-sm transition-all flex items-center space-x-1 flex-shrink-0 ${
            isListening
              ? 'bg-[#dc2626] text-white animate-pulse px-2'
              : 'bg-[#53c0aa] hover:bg-[#3fa792] active:scale-95 text-[#082923]'
          }`}
          title={isListening ? "Stop voice listening" : "Voice Command (Speech-to-Text)"}
        >
          <Mic className="w-3.5 h-3.5" />
          {isListening && <span className="text-[10px] font-mono font-bold tracking-wider">REC</span>}
        </button>
      </form>

      {/* Preset Action Chips */}
      <div className="flex flex-wrap items-center gap-1 text-[9px] sm:text-[10px] font-mono">
        <span className="text-[#20574b] uppercase font-bold mr-0.5">
          Protocols:
        </span>
        {presets.map((p) => {
          const Icon = p.icon;
          return (
            <button
              key={p.label}
              onClick={() => handlePresetClick(p.cmd)}
              disabled={isPlanning}
              className="flex items-center space-x-1 px-1.5 py-0.2 rounded-sm bg-[#b0ded4] hover:bg-[#53c0aa] active:scale-95 border border-[#26685c] font-bold text-[#082923] transition-all disabled:opacity-50 shadow-sm"
            >
              <Icon className="w-2.5 h-2.5 text-[#1b5b4e]" />
              <span>{p.label}</span>
            </button>
          );
        })}
      </div>
    </div>
  );
};
