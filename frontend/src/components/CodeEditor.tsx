import Editor from '@monaco-editor/react';

interface CodeEditorProps {
    code?: string;
    fileName?: string;
    language?: string;
    onChange?: (value: string | undefined) => void;
}

const getLanguageFromFileName = (fileName: string): string => {
    if (fileName.endsWith('.ts') || fileName.endsWith('.tsx')) return 'typescript';
    if (fileName.endsWith('.js') || fileName.endsWith('.jsx')) return 'javascript';
    if (fileName.endsWith('.json')) return 'json';
    if (fileName.endsWith('.css')) return 'css';
    if (fileName.endsWith('.html')) return 'html';
    if (fileName.endsWith('.md')) return 'markdown';
    return 'typescript';
};

export const CodeEditor = ({
    code = "// Start coding...",
    fileName,
    language,
    onChange
}: CodeEditorProps) => {
    const displayName = fileName ? fileName.split('/').pop() : 'Untitled';
    const editorLanguage = language || (fileName ? getLanguageFromFileName(fileName) : 'typescript');

    return (
        <div className="h-full w-full bg-[#1e1e1e] rounded-xl overflow-hidden shadow-lg border border-zinc-800">
            <div className="flex items-center justify-between px-4 py-2 bg-[#252526] border-b border-zinc-800">
                <div className="flex items-center gap-2">
                    <div className="flex gap-1.5">
                        <div className="w-3 h-3 rounded-full bg-red-500/80" />
                        <div className="w-3 h-3 rounded-full bg-yellow-500/80" />
                        <div className="w-3 h-3 rounded-full bg-green-500/80" />
                    </div>
                    <span className="text-xs text-zinc-400 ml-2 font-mono bg-zinc-800/50 px-2 py-0.5 rounded">
                        {displayName}
                    </span>
                </div>
                {fileName && (
                    <span className="text-xs text-zinc-600 font-mono truncate max-w-[200px]">
                        {fileName}
                    </span>
                )}
            </div>
            <Editor
                height="100%"
                language={editorLanguage}
                value={code}
                theme="vs-dark"
                onChange={onChange}
                options={{
                    minimap: { enabled: false },
                    fontSize: 14,
                    padding: { top: 16 },
                    fontFamily: "'JetBrains Mono', 'Fira Code', monospace",
                    scrollBeyondLastLine: false,
                    smoothScrolling: true,
                    cursorBlinking: "smooth",
                    cursorSmoothCaretAnimation: "on",
                    readOnly: true,
                    wordWrap: "on"
                }}
            />
        </div>
    );
};
