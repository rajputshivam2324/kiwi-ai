import React, { useState } from 'react';
import { motion } from 'framer-motion';

export interface FinanceCardData {
  title: string;
  data: Record<string, string | number>;
}

interface FinanceCardProps {
  cardData: FinanceCardData;
  agentName?: string;
}

export const FinanceCard: React.FC<FinanceCardProps> = ({ cardData, agentName }) => {
  const [rotateX, setRotateX] = useState(0);
  const [rotateY, setRotateY] = useState(0);

  const handleMouseMove = (e: React.MouseEvent<HTMLDivElement>) => {
    const card = e.currentTarget;
    const rect = card.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const y = e.clientY - rect.top;
    
    // Rotate relative to center, giving a realistic tilt effect
    const centerX = rect.width / 2;
    const centerY = rect.height / 2;
    const tiltX = ((y - centerY) / centerY) * -12; // Max 12 deg tilt
    const tiltY = ((x - centerX) / centerX) * 12;
    
    setRotateX(tiltX);
    setRotateY(tiltY);
  };

  const handleMouseLeave = () => {
    setRotateX(0);
    setRotateY(0);
  };

  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.95, y: 15 }}
      animate={{ opacity: 1, scale: 1, y: 0 }}
      transition={{ type: 'spring', stiffness: 350, damping: 25 }}
      style={{ perspective: 1500 }}
      className="my-5 relative w-full max-w-[380px]"
    >
      <motion.div
        onMouseMove={handleMouseMove}
        onMouseLeave={handleMouseLeave}
        animate={{ rotateX, rotateY }}
        transition={{ type: 'spring', stiffness: 400, damping: 30, mass: 0.5 }}
        className="w-full relative rounded-xl p-[1px] bg-gradient-to-br from-[#e2e8f0] via-[#94a3b8] to-[#475569] shadow-[0_15px_35px_rgba(0,0,0,0.3)] cursor-default overflow-hidden group"
        style={{ transformStyle: 'preserve-3d' }}
      >
        {/* Dynamic metallic sheen that follows the mouse tilt */}
        <div 
          className="absolute inset-0 opacity-0 group-hover:opacity-100 transition-opacity duration-300 pointer-events-none mix-blend-overlay z-50 rounded-xl"
          style={{
            background: `linear-gradient(${135 + rotateX + rotateY}deg, rgba(255,255,255,0.8) 0%, rgba(255,255,255,0) 40%, rgba(255,255,255,0.4) 100%)`
          }}
        />

        {/* Inner Card Background - Slate Silver Metallic */}
        <div 
          className="w-full h-full rounded-xl bg-gradient-to-br from-[#cbd5e1] via-[#f1f5f9] to-[#94a3b8] relative overflow-hidden flex flex-col"
          style={{ transform: 'translateZ(10px)', transformStyle: 'preserve-3d' }}
        >
          {/* Brushed Metal Texture Overlay */}
          <div className="absolute inset-0 opacity-[0.25] mix-blend-color-burn pointer-events-none bg-[url('https://www.transparenttextures.com/patterns/brushed-alum.png')]" />
          
          <div className="p-5 relative z-10 flex flex-col h-full">
            <motion.div 
               style={{ transform: 'translateZ(30px)' }}
               className="flex justify-between items-start mb-5 pb-3 border-b border-[#ffffff80]"
            >
              <div className="pr-2">
                <p className="text-[#64748b] text-[9px] font-bold uppercase tracking-[0.2em] mb-1 drop-shadow-sm">
                  {agentName ? `${agentName} Analysis` : 'Groww Finance'}
                </p>
                <h2 className="text-xl font-black text-[#0f172a] tracking-tight leading-tight drop-shadow-sm">
                  {cardData.title}
                </h2>
              </div>
              {/* Metallic Logo Badge */}
              <div className="w-8 h-8 rounded border border-[#ffffff90] flex items-center justify-center bg-gradient-to-br from-[#f8fafc] to-[#cbd5e1] shadow-inner flex-shrink-0">
                 <span className="text-[#334155] font-black text-sm">G</span>
              </div>
            </motion.div>

            {/* Metrics List */}
            <motion.div 
              style={{ transform: 'translateZ(20px)' }}
              className="space-y-3 relative z-10"
            >
              {Object.entries(cardData.data).map(([key, value]) => {
                 const displayValue = typeof value === 'object' ? JSON.stringify(value) : value.toString();
                 // Prevent rendering huge unformatted string blobs efficiently
                 if (displayValue.length > 80) return null;
                 
                 return (
                  <div key={key} className="flex justify-between items-center bg-[#f8fafc80] p-2.5 rounded border border-[#ffffff90] shadow-sm backdrop-blur-sm">
                    <span className="text-[11px] uppercase font-bold text-[#475569] tracking-wider truncate mr-4">
                      {key.replace(/_/g, ' ')}
                    </span>
                    <span className="text-[14px] font-bold text-[#0f172a] text-right truncate max-w-[160px]">
                      {displayValue}
                    </span>
                  </div>
                 )
              })}
            </motion.div>
          </div>
          
          {/* Bottom highlight edge */}
          <div className="absolute bottom-0 inset-x-0 h-[2px] bg-gradient-to-r from-[#94a3b8] via-[#ffffff] to-[#94a3b8] opacity-70" />
        </div>
      </motion.div>
    </motion.div>
  );
};
