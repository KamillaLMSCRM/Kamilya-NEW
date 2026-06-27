/**
 * JWT auth middleware for Kamilya backend service calls.
 *
 * Kamilya backend (Render) signs service-role JWTs with
 * KAMILYA_BACKEND_SECRET. Only the backend should be able to call
 * wa-gateway — never expose this gateway to the public internet.
 *
 * JWT payload expected:
 *   { sub: "kamilya-backend", role: "service", tenant_id?: "..." }
 */

'use strict';

const jwt = require('jsonwebtoken');

function authMiddleware(secret, logger) {
  return function (req, res, next) {
    const auth = req.headers.authorization || '';
    const match = auth.match(/^Bearer\s+(.+)$/i);
    if (!match) {
      return res.status(401).json({ detail: 'missing Authorization header' });
    }
    const token = match[1];

    try {
      const payload = jwt.verify(token, secret, { algorithms: ['HS256'] });
      if (payload.role !== 'service' && payload.role !== 'superadmin') {
        logger.warn({ payload }, 'auth: not a service token');
        return res.status(403).json({ detail: 'service role required' });
      }
      req.service = payload;
      next();
    } catch (err) {
      logger.warn({ err: err.message }, 'auth: token verification failed');
      return res.status(401).json({ detail: 'invalid token' });
    }
  };
}

module.exports = { authMiddleware };

/**
 * Helper: Kamilya backend uses this to mint a service JWT for its
 * outbound calls to wa-gateway. Tokens are short-lived (5 min) — gateway
 * is called many times per minute, so each call gets a fresh token.
 */
function signServiceToken(secret, opts = {}) {
  return jwt.sign(
    {
      sub: 'kamilya-backend',
      role: 'service',
      ...opts,
    },
    secret,
    { algorithm: 'HS256', expiresIn: '5m' }
  );
}

module.exports.signServiceToken = signServiceToken;