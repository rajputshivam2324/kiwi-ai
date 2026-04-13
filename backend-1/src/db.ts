import pg from 'pg';
import dotenv from 'dotenv';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

dotenv.config({ path: path.join(__dirname, '.env') });

const pool = new pg.Pool({
    connectionString: process.env.DATABASE_URL || 'postgresql://kiwi:kiwi_secret_2024@localhost:5432/kiwi_ai',
});

export const initDb = async () => {
    const client = await pool.connect();
    try {
        await client.query(`
            CREATE TABLE IF NOT EXISTS projects (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                name TEXT NOT NULL,
                prompt TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'queued',
                dev_port INTEGER,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            );

            CREATE INDEX IF NOT EXISTS idx_projects_user_id ON projects(user_id);

            CREATE TABLE IF NOT EXISTS project_files (
                id SERIAL PRIMARY KEY,
                project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                file_path TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                UNIQUE(project_id, file_path)
            );

            CREATE INDEX IF NOT EXISTS idx_project_files_project_id ON project_files(project_id);
        `);
        console.log('✅ Database tables initialized');
    } finally {
        client.release();
    }
};

// Project operations
export const createProject = async (id: string, userId: string, name: string, prompt: string) => {
    await pool.query(
        'INSERT INTO projects (id, user_id, name, prompt, status) VALUES ($1, $2, $3, $4, $5)',
        [id, userId, name, prompt, 'queued']
    );
};

export const updateProjectStatus = async (id: string, status: string, devPort?: number) => {
    if (devPort !== undefined) {
        await pool.query(
            'UPDATE projects SET status = $1, dev_port = $2, updated_at = NOW() WHERE id = $3',
            [status, devPort, id]
        );
    } else {
        await pool.query(
            'UPDATE projects SET status = $1, updated_at = NOW() WHERE id = $2',
            [status, id]
        );
    }
};

export const getProjectsByUser = async (userId: string) => {
    const result = await pool.query(
        'SELECT id, name, status, prompt, dev_port, created_at, updated_at FROM projects WHERE user_id = $1 ORDER BY created_at DESC',
        [userId]
    );
    return result.rows;
};

export const getProjectById = async (id: string) => {
    const result = await pool.query('SELECT * FROM projects WHERE id = $1', [id]);
    return result.rows[0] || null;
};

export const getProjectByIdAndUser = async (id: string, userId: string) => {
    const result = await pool.query('SELECT * FROM projects WHERE id = $1 AND user_id = $2', [id, userId]);
    return result.rows[0] || null;
};

// File operations
export const saveProjectFiles = async (projectId: string, files: Array<{ path: string; content: string }>) => {
    const client = await pool.connect();
    try {
        await client.query('BEGIN');
        for (const file of files) {
            await client.query(
                `INSERT INTO project_files (project_id, file_path, content) 
                 VALUES ($1, $2, $3) 
                 ON CONFLICT (project_id, file_path) DO UPDATE SET content = $3`,
                [projectId, file.path, file.content]
            );
        }
        await client.query('COMMIT');
    } catch (e) {
        await client.query('ROLLBACK');
        throw e;
    } finally {
        client.release();
    }
};

export const getProjectFiles = async (projectId: string) => {
    const result = await pool.query(
        'SELECT file_path, content FROM project_files WHERE project_id = $1 ORDER BY file_path',
        [projectId]
    );
    return result.rows;
};

export const getProjectFileContent = async (projectId: string, filePath: string) => {
    const result = await pool.query(
        'SELECT content FROM project_files WHERE project_id = $1 AND file_path = $2',
        [projectId, filePath]
    );
    return result.rows[0]?.content || null;
};

export default pool;
