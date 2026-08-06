import { motion } from 'framer-motion';
import { 
  TrendingUp, Code2, BookOpen, MessageCircle, Search, 
  Layers, Zap, Sparkles, Brain, 
  Plus, Mic, ArrowUp, ArrowRight, Github, Twitter, Linkedin
} from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import kiwiHero from '../assets/kiwi-hero.png';
import { useState, useEffect } from 'react';

export const LandingPage = () => {
  const navigate = useNavigate();
  const [scrolled, setScrolled] = useState(false);
  const [isMobileMenuOpen, setIsMobileMenuOpen] = useState(false);

  useEffect(() => {
    const handleScroll = () => {
      setScrolled(window.scrollY > 20);
    };
    window.addEventListener('scroll', handleScroll);
    return () => window.removeEventListener('scroll', handleScroll);
  }, []);

  const theme = {
    bg: 'bg-[#FCFBF8]', // hsl(40 33% 98%)
    primary: 'text-[#5C4A3D]', // hsl(30 20% 30%)
    accentText: 'text-[#B8627D]', // hsl(340 30% 55%)
    primaryBg: 'bg-[#5C4A3D]',
    accentBg: 'bg-[#B8627D]',
  };

  const fadeInUp = {
    initial: { opacity: 0, y: 30 },
    whileInView: { opacity: 1, y: 0 },
    viewport: { once: true },
    transition: { duration: 0.6, ease: "easeOut" as const }
  };

  const navLinks = [
    { name: 'Features', href: '#features' },
    { name: 'Modes', href: '#modes' },
    { name: 'Docs', href: '#docs' },
  ];

  return (
    <div className={`min-h-screen ${theme.bg} ${theme.primary} font-inter overflow-x-hidden selection:bg-[#B8627D]/20`}>
      {/* 1. Navbar */}
      <nav className={`fixed top-0 left-0 right-0 z-50 transition-all duration-300 ${scrolled ? 'glass shadow-sm py-3' : 'bg-transparent py-5'}`}>
        <div className="max-w-7xl mx-auto px-6 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="font-caudex font-bold text-2xl tracking-tight">Kiwi AI</span>
          </div>

          {/* Desktop Nav */}
          <div className="hidden md:flex items-center gap-8">
            {navLinks.map((link) => (
              <a key={link.name} href={link.href} className="text-sm font-medium opacity-70 hover:opacity-100 transition-opacity">
                {link.name}
              </a>
            ))}
          </div>

          <div className="hidden md:flex items-center gap-4">
            <button 
              onClick={() => navigate('/auth')} 
              className="px-5 py-2 text-sm font-medium opacity-80 hover:opacity-100 transition-all"
            >
              Sign In
            </button>
            <button 
              onClick={() => navigate('/auth')} 
              className="px-6 py-2.5 text-sm font-medium text-white rounded-full bg-gradient-to-r from-[#5C4A3D] to-[#40332A] hover:shadow-lg hover:scale-105 transition-all shadow-md"
            >
              Get Started
            </button>
          </div>

          {/* Mobile hamburger */}
          <button 
            className="md:hidden p-2"
            onClick={() => setIsMobileMenuOpen(!isMobileMenuOpen)}
          >
            <div className="w-6 h-0.5 bg-current mb-1.5"></div>
            <div className="w-6 h-0.5 bg-current mb-1.5"></div>
            <div className="w-6 h-0.5 bg-current"></div>
          </button>
        </div>

        {/* Mobile Nav */}
        {isMobileMenuOpen && (
          <div className="absolute top-full left-0 right-0 glass border-t border-[#5C4A3D]/10 p-4 flex flex-col gap-4 md:hidden">
            {navLinks.map((link) => (
              <a key={link.name} href={link.href} className="text-sm font-medium px-4 py-2" onClick={() => setIsMobileMenuOpen(false)}>
                {link.name}
              </a>
            ))}
            <div className="h-px bg-[#5C4A3D]/10 my-2" />
            <button onClick={() => { navigate('/auth'); setIsMobileMenuOpen(false); }} className="text-left px-4 py-2 font-medium">Sign In</button>
            <button onClick={() => { navigate('/auth'); setIsMobileMenuOpen(false); }} className="mx-4 py-3 text-center text-white rounded-full bg-gradient-to-r from-[#5C4A3D] to-[#40332A]">
              Get Started
            </button>
          </div>
        )}
      </nav>

      {/* 2. Hero Section */}
      <section className="relative pt-32 pb-20 min-h-[90vh] flex flex-col items-center justify-center overflow-hidden text-center">
        {/* Bright radial glow behind kiwi */}
        <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-[60%] w-[800px] h-[800px] bg-white/90 rounded-full blur-[80px] -z-10 pointer-events-none" />
        
        <div className="max-w-4xl mx-auto px-6 flex flex-col items-center justify-center relative z-10 w-full">
          <motion.div 
            initial={{ opacity: 0, scale: 0.9 }}
            animate={{ opacity: 1, scale: 1 }}
            transition={{ duration: 1 }}
            className="flex justify-center mb-6 w-full"
          >
            <motion.img 
              src={kiwiHero} 
              alt="Kiwi AI Mascot" 
              className="w-full max-w-[320px] md:max-w-[400px] drop-shadow-2xl object-contain"
              animate={{ y: [0, -15, 0] }}
              transition={{ repeat: Infinity, duration: 4, ease: "easeInOut" }}
            />
          </motion.div>

          <motion.div {...fadeInUp} className="max-w-4xl flex flex-col items-center">
            <h1 className="font-caudex text-6xl md:text-[5.5rem] font-bold mb-6 leading-[1] tracking-tight">
              One AI. <span className="text-transparent bg-clip-text bg-gradient-to-r from-[#B8627D] to-[#8C4B5F]">Every Mode<br/>You Need.</span>
            </h1>
            <p className="text-base md:text-lg opacity-70 mb-10 leading-relaxed max-w-xl mx-auto text-[#5C4A3D]/90 font-medium">
              Finance, build, research, and chat — all in one<br />intelligent system.
            </p>
            <button 
              onClick={() => navigate('/auth')}
              className="flex items-center gap-2 px-8 py-3.5 text-sm font-medium text-white rounded-full bg-[#4a3b31] hover:bg-[#3d3129] transition-all shadow-md group"
            >
              Get Started
              <ArrowRight className="w-4 h-4 group-hover:translate-x-1 transition-transform" />
            </button>
          </motion.div>
        </div>
      </section>

      {/* 3. Modes Section */}
      <section id="modes" className="py-24 px-6 relative z-10">
        <div className="max-w-7xl mx-auto">
          <motion.div {...fadeInUp} className="text-center mb-16">
            <h2 className="font-caudex text-4xl md:text-5xl font-bold mb-4">Four Modes. Infinite Possibilities.</h2>
          </motion.div>

          <div className="grid md:grid-cols-2 gap-6">
            {[
              { icon: TrendingUp, title: "Finance Mode", desc: "Analyze markets, track trends, and make smarter financial decisions." },
              { icon: Code2, title: "Build Mode", desc: "Create apps, tools, and systems — just like ChatGPT, but more powerful." },
              { icon: MessageCircle, title: "Chat Mode", desc: "Fast, natural conversations for everyday use." },
              { icon: Search, title: "Research Mode", desc: "Deep insights, structured answers, and intelligent exploration." }
            ].map((mode, i) => (
              <motion.div 
                key={mode.title}
                initial={{ opacity: 0, y: 30 }}
                whileInView={{ opacity: 1, y: 0 }}
                viewport={{ once: true }}
                transition={{ delay: i * 0.1, duration: 0.5 }}
                className="glass-card p-8 rounded-3xl hover:-translate-y-1 transition-transform duration-300 group cursor-default"
              >
                <div className="w-14 h-14 rounded-2xl bg-gradient-to-br from-[#FCFBF8] to-[#EAE6DE] flex items-center justify-center mb-6 shadow-sm border border-[#5C4A3D]/5">
                  <mode.icon className="w-6 h-6 text-[#B8627D] group-hover:scale-110 transition-transform" />
                </div>
                <h3 className="font-caudex text-2xl font-bold mb-3">{mode.title}</h3>
                <p className="opacity-75 leading-relaxed">{mode.desc}</p>
              </motion.div>
            ))}
          </div>
        </div>
      </section>

      {/* 4. Why Kiwi AI Section */}
      <section id="features" className="py-24 px-6 bg-[#F6F4EF] border-y border-[#5C4A3D]/5">
        <div className="max-w-7xl mx-auto">
          <motion.div {...fadeInUp} className="text-center mb-20">
            <h2 className="font-caudex text-4xl md:text-5xl font-bold">Why Kiwi AI?</h2>
          </motion.div>

          <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-8">
            {[
              { icon: Layers, title: "Unified AI System" },
              { icon: Zap, title: "Lightning-Fast Responses" },
              { icon: Sparkles, title: "Beautiful Interface" },
              { icon: Brain, title: "Multi-Mode Intelligence" }
            ].map((feature, i) => (
              <motion.div 
                key={feature.title}
                initial={{ opacity: 0, scale: 0.9 }}
                whileInView={{ opacity: 1, scale: 1 }}
                viewport={{ once: true }}
                transition={{ delay: i * 0.1 }}
                className="flex flex-col items-center text-center"
              >
                <div className="w-16 h-16 rounded-full bg-gradient-to-br from-[#B8627D] to-[#8C4B5F] flex items-center justify-center mb-6 shadow-lg shadow-[#B8627D]/20">
                  <feature.icon className="w-7 h-7 text-white" />
                </div>
                <h3 className="font-caudex font-bold text-xl">{feature.title}</h3>
              </motion.div>
            ))}
          </div>
        </div>
      </section>

      {/* 5. Demo Section */}
      <section className="py-24 md:py-32 relative">
        <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[800px] h-[400px] bg-gradient-to-r from-red-100/40 via-purple-100/40 to-blue-50/40 rounded-full blur-[100px] -z-10 pointer-events-none" />
        <div className="max-w-7xl mx-auto px-6">
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true }}
            className="text-center mb-12"
          >
            <h2 className="text-3xl md:text-4xl font-bold tracking-tight font-caudex">
              See It <span className="text-transparent bg-clip-text bg-gradient-to-r from-[#B8627D] to-[#8C4B5F]">In Action</span>
            </h2>
            <p className="mt-4 text-[#5C4A3D]/70 text-lg max-w-md mx-auto">
              Watch how Kiwi AI seamlessly switches between modes.
            </p>
          </motion.div>

          <motion.div
            initial={{ opacity: 0, scale: 0.95 }}
            whileInView={{ opacity: 1, scale: 1 }}
            viewport={{ once: true }}
            transition={{ duration: 0.5 }}
            className="max-w-3xl mx-auto"
          >
            {/* Chat interface mockup based on Kiwi AI design */}
            <div className="flex flex-col items-center justify-center py-16">
              <h3 className="text-3xl md:text-4xl mb-10 text-center tracking-tight text-[#5C4A3D]">
                <span className="font-caudex italic text-[#5C4A3D]/70 mr-1">Hi,</span>{" "}
                <span className="font-inter">how can </span>
                <span className="font-inter font-bold">I help </span>
                <span className="font-caudex italic text-[#B8627D]">you</span>
                <span className="font-inter"> today?</span>
              </h3>

              <div className="w-full max-w-2xl bg-white shadow-[0_8px_30px_rgb(0,0,0,0.06)] border border-black/5 rounded-[2rem] p-4">
                {/* Input area */}
                <div className="flex items-center gap-3 mb-3 px-2 pt-1">
                  <input
                    type="text"
                    placeholder="Type a message..."
                    className="flex-1 bg-transparent text-[#5C4A3D] placeholder:text-[#9CA3AF] outline-none text-sm font-inter"
                    readOnly
                  />
                  <div className="w-8 h-8 rounded-full bg-[#B8627D]/10 flex items-center justify-center text-[#B8627D] text-xs font-bold font-inter shrink-0">
                    K
                  </div>
                </div>

                {/* Bottom toolbar */}
                <div className="flex items-center justify-between px-1 mt-6">
                  <div className="flex items-center gap-2">
                    <button className="p-2 text-[#9CA3AF] hover:text-[#5C4A3D] transition-colors rounded-lg">
                      <Plus size={18} />
                    </button>
                    <button className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-[#9CA3AF] hover:text-[#5C4A3D] transition-colors rounded-lg font-inter">
                      <BookOpen size={15} /> Research
                    </button>
                    <button className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-[#9CA3AF] hover:text-[#5C4A3D] transition-colors rounded-lg font-inter">
                      <TrendingUp size={15} /> Finance
                    </button>
                  </div>
                  <div className="flex items-center gap-2">
                    <button className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-[#9CA3AF] hover:text-[#5C4A3D] transition-colors rounded-lg font-inter pr-4">
                      <Code2 size={15} /> Build
                    </button>
                    <button className="p-2 text-[#9CA3AF] hover:text-[#5C4A3D] transition-colors rounded-lg">
                      <Mic size={18} />
                    </button>
                    <button className="p-2 text-[#6B7280] hover:text-[#5C4A3D] transition-colors rounded-2xl border border-black/10 bg-[#F3F4F6] hover:bg-[#E5E7EB]">
                      <ArrowUp size={16} />
                    </button>
                  </div>
                </div>
              </div>
            </div>
          </motion.div>
        </div>
      </section>

      {/* 6. Testimonials Section */}
      <section className="py-24 px-6 bg-[#F6F4EF] border-y border-[#5C4A3D]/5">
        <div className="max-w-7xl mx-auto">
          <motion.div {...fadeInUp} className="text-center mb-16">
            <h2 className="font-caudex text-4xl md:text-5xl font-bold">Loved by Early Adopters</h2>
          </motion.div>

          <div className="grid md:grid-cols-3 gap-8">
            {[
              { text: "Kiwi AI replaced three tools in my workflow. The mode switching is seamless.", author: "Sarah Chen", role: "Product Designer" },
              { text: "Build Mode is incredible — I shipped a prototype in minutes, not days.", author: "Marcus Rivera", role: "Software Engineer" },
              { text: "Finally, an AI that actually understands financial context.", author: "Aisha Patel", role: "Financial Analyst" }
            ].map((t, i) => (
              <motion.div 
                key={i}
                initial={{ opacity: 0, y: 30 }}
                whileInView={{ opacity: 1, y: 0 }}
                viewport={{ once: true }}
                transition={{ delay: i * 0.1 }}
                className="glass-card p-8 rounded-3xl"
              >
                <p className="text-lg leading-relaxed mb-6 block opacity-90">"{t.text}"</p>
                <div>
                  <p className="font-bold font-caudex text-lg">{t.author}</p>
                  <p className="opacity-60 text-sm">{t.role}</p>
                </div>
              </motion.div>
            ))}
          </div>
        </div>
      </section>

      {/* 7. CTA Section */}
      <section className="py-32 px-6 text-center">
        <motion.div {...fadeInUp} className="max-w-3xl mx-auto">
          <h2 className="font-caudex text-5xl md:text-6xl font-bold mb-6">Start building with Kiwi AI today.</h2>
          <p className="text-xl opacity-75 mb-10">Join thousands of users who are already working smarter.</p>
          <button 
            onClick={() => navigate('/auth')}
            className="px-10 py-4 text-lg font-medium text-white rounded-full bg-gradient-to-r from-[#B8627D] to-[#8C4B5F] hover:shadow-xl hover:scale-105 transition-all shadow-lg"
          >
            Get Started Free
          </button>
        </motion.div>
      </section>

      {/* 8. Footer */}
      <footer className="bg-[#EAE6DE]/50 pt-20 pb-10 px-6 border-t border-[#5C4A3D]/10">
        <div className="max-w-7xl mx-auto">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-10 mb-16">
            <div className="col-span-2 md:col-span-1">
              <span className="font-caudex font-bold text-2xl tracking-tight block mb-4">Kiwi AI</span>
              <p className="opacity-70 text-sm leading-relaxed pr-4">
                The unified AI platform for financing, building, researching, and conversing seamlessly.
              </p>
            </div>
            
            <div>
              <h4 className="font-bold mb-4 font-caudex">Product</h4>
              <ul className="space-y-3 text-sm opacity-70">
                <li><a href="#" className="hover:opacity-100 transition-opacity whitespace-nowrap">Features</a></li>
                <li><a href="#modes" className="hover:opacity-100 transition-opacity whitespace-nowrap">Modes</a></li>
                <li><a href="#" className="hover:opacity-100 transition-opacity whitespace-nowrap">Pricing</a></li>
              </ul>
            </div>
            
            <div>
              <h4 className="font-bold mb-4 font-caudex">Resources</h4>
              <ul className="space-y-3 text-sm opacity-70">
                <li><a href="#" className="hover:opacity-100 transition-opacity whitespace-nowrap">Documentation</a></li>
                <li><a href="#" className="hover:opacity-100 transition-opacity whitespace-nowrap">Blog</a></li>
                <li><a href="#" className="hover:opacity-100 transition-opacity whitespace-nowrap">Support</a></li>
              </ul>
            </div>
            
            <div>
              <h4 className="font-bold mb-4 font-caudex">Legal</h4>
              <ul className="space-y-3 text-sm opacity-70">
                <li><a href="#" className="hover:opacity-100 transition-opacity whitespace-nowrap">Privacy Policy</a></li>
                <li><a href="#" className="hover:opacity-100 transition-opacity whitespace-nowrap">Terms of Service</a></li>
                <li><a href="#" className="hover:opacity-100 transition-opacity whitespace-nowrap">Security</a></li>
              </ul>
            </div>
          </div>

          <div className="pt-8 border-t border-[#5C4A3D]/20 flex flex-col md:flex-row items-center justify-between gap-4">
            <p className="text-sm opacity-60">© {new Date().getFullYear()} Kiwi AI. All rights reserved.</p>
            <div className="flex gap-4 opacity-60">
              <a href="#" className="hover:opacity-100 transition-opacity"><Twitter className="w-5 h-5" /></a>
              <a href="#" className="hover:opacity-100 transition-opacity"><Github className="w-5 h-5" /></a>
              <a href="#" className="hover:opacity-100 transition-opacity"><Linkedin className="w-5 h-5" /></a>
            </div>
          </div>
        </div>
      </footer>
    </div>
  );
};
