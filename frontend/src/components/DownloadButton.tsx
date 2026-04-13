import React, { useState } from 'react';
import { Download, Loader2 } from 'lucide-react';
import { useAuth } from '@clerk/clerk-react';

interface DownloadButtonProps {
    jobId: string | null;
    disabled?: boolean;
}

export const DownloadButton: React.FC<DownloadButtonProps> = ({ jobId, disabled }) => {
    const { getToken } = useAuth();
    const [isDownloading, setIsDownloading] = useState(false);

    const handleDownload = async () => {
        if (!jobId || isDownloading) return;

        setIsDownloading(true);
        try {
            const token = await getToken();
            const response = await fetch(`http://localhost:4000/api/build/download/${jobId}`, {
                headers: token ? { 'Authorization': `Bearer ${token}` } : {},
                credentials: 'include',
            });
            if (!response.ok) throw new Error('Download failed');

            const blob = await response.blob();
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `${jobId}.zip`;
            document.body.appendChild(a);
            a.click();
            window.URL.revokeObjectURL(url);
            document.body.removeChild(a);
        } catch (error) {
            console.error('Download failed:', error);
        } finally {
            setIsDownloading(false);
        }
    };

    return (
        <button
            onClick={handleDownload}
            disabled={disabled || !jobId || isDownloading}
            className="flex items-center gap-2 px-3 py-1.5 text-sm font-medium text-zinc-300 bg-zinc-800 hover:bg-zinc-700 disabled:opacity-50 disabled:cursor-not-allowed rounded-lg transition-colors border border-zinc-700"
        >
            {isDownloading ? (
                <Loader2 size={14} className="animate-spin" />
            ) : (
                <Download size={14} />
            )}
            Download
        </button>
    );
};
