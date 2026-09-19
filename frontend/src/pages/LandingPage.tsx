import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { 
  Bot, 
  Terminal, 
  User, 
  ChevronRight, 
  ArrowRight,
  Play
} from 'lucide-react';
import { UserAuth } from '../types/robosurge';
import { Heart3D } from '../components/Heart3D';

interface LandingPageProps {
  user: UserAuth | null;
}

export const LandingPage: React.FC<LandingPageProps> = ({ user }) => {
  const navigate = useNavigate();
  const [timeStr, setTimeStr] = useState('');

  useEffect(() => {
    const updateTime = () => {
      const now = new Date();
      setTimeStr(now.toTimeString().split(' ')[0]);
    };
    updateTime();
    const timer = setInterval(updateTime, 1000);
    return () => clearInterval(timer);
  }, []);

  return (
    <div className="min-h-screen w-full bg-white text-black flex flex-col font-sans selection:bg-neutral-200 selection:text-black relative overflow-hidden select-none">
      
      {/* 3D Realistic Heart Background Layer (Pure White Canvas) */}
      <div className="absolute inset-0 z-0 bg-white">
        <Heart3D className="w-full h-full" />
      </div>

      {/* Top Minimalist Navbar (Pure White Glassmorphism) */}
      <nav className="relative z-20 bg-white/70 backdrop-blur-md border-b border-neutral-200/80 px-4 sm:px-8 py-3.5 shadow-sm">
        <div className="max-w-7xl mx-auto flex items-center justify-between">
          
          {/* Brand Logo */}
          <div className="flex items-center space-x-3 cursor-pointer" onClick={() => navigate('/')}>
            <div className="flex items-center justify-center w-8 h-8 rounded-lg bg-black text-white shadow-md">
              <Bot className="w-5 h-5" />
            </div>
            <div className="flex items-baseline space-x-2">
              <span className="font-black tracking-wider text-base text-black font-mono">
                ROBOSURGE
              </span>
              <span className="text-[11px] font-mono tracking-widest text-neutral-500 uppercase font-bold">
                SYSTEM OS
              </span>
            </div>
          </div>

          {/* Right Action / Status */}
          <div className="flex items-center space-x-3">
            <div className="hidden sm:block text-xs font-mono text-neutral-500 font-medium px-2">
              UTC {timeStr}
            </div>

            {user ? (
              <button
                onClick={() => navigate('/console')}
                className="px-4 py-1.5 rounded-lg bg-neutral-900 hover:bg-black text-white font-mono font-bold text-xs border border-neutral-900 transition-all flex items-center space-x-1.5 shadow-md"
              >
                <Terminal className="w-3.5 h-3.5" />
                <span>CONSOLE ({user.username})</span>
                <ArrowRight className="w-3.5 h-3.5" />
              </button>
            ) : (
              <>
                <button
                  onClick={() => navigate('/auth')}
                  className="px-3.5 py-1.5 rounded-lg bg-neutral-100 hover:bg-neutral-200 text-black font-mono font-bold text-xs border border-neutral-300 transition-colors flex items-center space-x-1"
                >
                  <User className="w-3.5 h-3.5 text-neutral-700" />
                  <span>SIGN IN</span>
                </button>
                <button
                  onClick={() => navigate('/console')}
                  className="px-4 py-1.5 rounded-lg bg-black hover:bg-neutral-800 text-white font-mono font-black text-xs border border-black transition-all flex items-center space-x-1.5 shadow-md"
                >
                  <Play className="w-3.5 h-3.5 fill-current" />
                  <span>CONSOLE</span>
                </button>
              </>
            )}
          </div>
        </div>
      </nav>

      {/* Hero Center Overlay with High-Contrast Frosted Backing */}
      <main className="relative z-10 flex-1 flex flex-col items-center justify-center px-4 sm:px-8 text-center pointer-events-none pb-8">
        <div className="max-w-4xl space-y-8 pointer-events-auto flex flex-col items-center">
          
          {/* Main Title with Frosted Backdrop Card for 100% Crystal Contrast */}
          <div className="bg-white/80 backdrop-blur-md px-6 sm:px-12 py-4 sm:py-6 rounded-3xl border border-neutral-200/90 shadow-2xl inline-block">
            <h1 className="text-4xl sm:text-6xl lg:text-7xl font-black font-mono tracking-tight text-black leading-tight uppercase select-text">
              Vulnera Sanentur
            </h1>
          </div>

          {/* Action CTAs */}
          <div className="flex flex-wrap items-center justify-center gap-4 pt-1">
            <button
              onClick={() => navigate('/console')}
              className="px-8 py-4 rounded-2xl bg-black hover:bg-neutral-800 active:scale-95 text-white font-mono font-black text-sm sm:text-base tracking-wider uppercase shadow-2xl transition-all flex items-center space-x-2 border-2 border-black"
            >
              <Terminal className="w-4 h-4" />
              <span>Launch Surgeon Console</span>
              <ChevronRight className="w-4 h-4" />
            </button>

            <button
              onClick={() => navigate('/auth')}
              className="px-7 py-4 rounded-2xl bg-white/95 hover:bg-neutral-100 active:scale-95 backdrop-blur-md text-black font-mono font-bold text-sm sm:text-base border-2 border-black shadow-xl transition-all flex items-center space-x-2"
            >
              <User className="w-4 h-4 text-neutral-700" />
              <span>Doctor Authorization</span>
            </button>
          </div>

        </div>
      </main>

    </div>
  );
};
