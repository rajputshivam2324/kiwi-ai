import { motion } from 'framer-motion';
import { Sparkles } from 'lucide-react';
import { SignIn } from '@clerk/clerk-react';

export const AuthLandingPage = () => {

  return (
    <div className="min-h-screen bg-[#FCFBF8] font-inter flex items-center justify-center p-4 relative overflow-hidden">
      {/* Background Gradients */}
      <div className="absolute inset-0 overflow-hidden pointer-events-none">
        <div className="absolute -top-[20%] -left-[10%] w-[50%] h-[80%] bg-red-100/40 blur-[120px] rounded-full mix-blend-multiply" />
        <div className="absolute -bottom-[20%] -right-[10%] w-[50%] h-[80%] bg-[#B8627D]/10 blur-[120px] rounded-full mix-blend-multiply" />
        <div className="absolute top-[30%] left-[30%] w-[40%] h-[40%] bg-[#5C4A3D]/5 blur-[100px] rounded-full mix-blend-multiply" />
      </div>

      <div className="w-full max-w-5xl relative z-10 flex gap-12 items-center">
        {/* Left Side - Hero */}
        <motion.div
          initial={{ opacity: 0, x: -20 }}
          animate={{ opacity: 1, x: 0 }}
          className="flex-1 hidden lg:block"
        >
          <div className="flex items-center gap-3 mb-8">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-[#B8627D] to-[#8C4B5F] flex items-center justify-center shadow-md">
              <Sparkles className="w-5 h-5 text-white" />
            </div>
            <span className="text-2xl font-bold font-caudex text-[#2C2420]">Kiwi AI</span>
          </div>

          <h1 className="text-5xl font-caudex font-bold text-[#2C2420] mb-6 leading-tight">
            Intelligence Powered By{' '}
            <span className="text-transparent bg-clip-text bg-gradient-to-r from-[#B8627D] to-[#8C4B5F]">
              Kiwi AI
            </span>
          </h1>

          <p className="text-[#5C4A3D]/70 font-inter text-lg mb-8 leading-relaxed">
            Create stunning web applications in minutes. Just describe what you want,
            and our AI will generate production-ready code with beautiful designs.
            Chat with Finance and Research Agent for more Insights.
          </p>

          <div className="flex flex-wrap gap-4 font-inter">
            <div className="flex items-center gap-2 px-4 py-2 bg-white/60 backdrop-blur-sm rounded-lg border border-black/5 shadow-sm">
              <div className="w-2 h-2 rounded-full bg-green-500" />
              <span className="text-[#5C4A3D]/80 text-sm font-medium">AI Code Generation</span>
            </div>
            <div className="flex items-center gap-2 px-4 py-2 bg-white/60 backdrop-blur-sm rounded-lg border border-black/5 shadow-sm">
              <div className="w-2 h-2 rounded-full bg-blue-500" />
              <span className="text-[#5C4A3D]/80 text-sm font-medium">Live Preview</span>
            </div>
            <div className="flex items-center gap-2 px-4 py-2 bg-white/60 backdrop-blur-sm rounded-lg border border-black/5 shadow-sm">
              <div className="w-2 h-2 rounded-full bg-[#B8627D]" />
              <span className="text-[#5C4A3D]/80 text-sm font-medium">Finance & Research Agents</span>
            </div>
          </div>
        </motion.div>

        {/* Right Side - Clerk SignIn */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          className="w-full max-w-md"
        >
          <div className="flex justify-center w-full">
            <SignIn 
              appearance={{
                elements: {
                  rootBox: "w-full",
                  card: "bg-white/80 backdrop-blur-lg border border-black/5 rounded-[2rem] shadow-[0_8px_30px_rgb(0,0,0,0.06)] w-full max-w-md",
                  headerTitle: "text-[#2C2420] text-3xl font-bold font-caudex",
                  headerSubtitle: "text-[#5C4A3D]/70 text-sm font-inter",
                  socialButtonsBlockButton: "bg-[#F3F4F6] hover:bg-[#E5E7EB] border border-black/5 text-[#5C4A3D] transition-colors font-inter shadow-sm",
                  socialButtonsBlockButtonText: "text-[#5C4A3D] font-semibold",
                  socialButtonsBlockButtonArrow: "text-[#5C4A3D]",
                  dividerLine: "bg-black/10",
                  dividerText: "text-[#5C4A3D]/50 bg-transparent font-inter",
                  formFieldLabel: "text-[#5C4A3D]/80 font-inter font-medium",
                  formFieldInput: "bg-white border-black/10 text-[#5C4A3D] focus:border-[#B8627D] focus:ring-[#B8627D]/20 shadow-sm font-inter",
                  formButtonPrimary: "bg-gradient-to-r from-[#B8627D] to-[#8C4B5F] hover:from-[#A5566F] hover:to-[#7E4254] hover:shadow-lg text-white font-semibold transition-all font-inter rounded-xl",
                  footerActionText: "text-[#5C4A3D]/70 font-inter",
                  footerActionLink: "text-[#B8627D] hover:text-[#8C4B5F] font-inter font-semibold",
                  identityPreviewText: "text-[#5C4A3D] font-inter",
                  identityPreviewEditButtonIcon: "text-[#B8627D]"
                }
              }}
            />
          </div>
        </motion.div>
      </div>
    </div>
  );
};
