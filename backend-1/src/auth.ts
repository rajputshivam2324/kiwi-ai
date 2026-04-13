import { clerkMiddleware, getAuth, requireAuth as clerkRequireAuth } from '@clerk/express';
import type { Request, Response, NextFunction } from 'express';

// Extend Express Request to include userId
declare global {
    namespace Express {
        interface Request {
            userId?: string;
        }
    }
}

// Base Clerk middleware - initializes Clerk for all routes
export const clerkAuth = clerkMiddleware();

// Middleware that requires authentication and extracts userId
export const requireAuth = (req: Request, res: Response, next: NextFunction) => {
    const auth = getAuth(req);
    if (!auth?.userId) {
        res.status(401).json({ error: 'Unauthorized' });
        return;
    }
    req.userId = auth.userId;
    next();
};

// For SSE endpoints where token comes via query parameter
export const optionalAuth = (req: Request, res: Response, next: NextFunction) => {
    const auth = getAuth(req);
    if (auth?.userId) {
        req.userId = auth.userId;
    }
    next();
};
