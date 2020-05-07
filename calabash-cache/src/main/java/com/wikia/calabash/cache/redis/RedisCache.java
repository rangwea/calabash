package com.wikia.calabash.cache.redis;

import com.wikia.calabash.cache.Cache;
import com.wikia.calabash.cache.CacheException;
import com.wikia.calabash.cache.FastJsonSerializer;
import com.wikia.calabash.cache.KeyParser;
import com.wikia.calabash.cache.Serializer;
import com.wikia.calabash.cache.SpelKeyParser;
import lombok.extern.slf4j.Slf4j;
import org.aspectj.lang.ProceedingJoinPoint;
import org.springframework.data.redis.core.RedisTemplate;

import java.lang.reflect.Method;
import java.lang.reflect.Type;

@Slf4j
public class RedisCache implements Cache {
    private RedisTemplate<String, String> redisTemplate;
    // 暂时不允许定制化
    private Serializer serializer = new FastJsonSerializer();
    // 暂时不允许定制化
    private KeyParser keyParser = new SpelKeyParser();

    private Type cacheReturnType;
    private RedisCached redisCached;
    private Method cachedMethod;

    public RedisCache(RedisTemplate<String, String> redisTemplate, Method cachedMethod, RedisCached redisCached) {
        this.redisTemplate = redisTemplate;
        this.cachedMethod = cachedMethod;
        this.cacheReturnType = cachedMethod.getGenericReturnType();
        this.redisCached = redisCached;
    }

    public Object computeIfAbsent(ProceedingJoinPoint joinPoint) throws Throwable {
        try {
            String key = keyParser.generateKey(redisCached.name(), redisCached.key(), cachedMethod, joinPoint.getArgs());
            Object obj = this.get(key);
            if (obj == null) {
                synchronized (this) {
                    obj = joinPoint.proceed();
                    if (obj != null) {
                        this.put(key, obj);
                    }
                    if (log.isDebugEnabled()) {
                        log.debug("redis cache not hit:key={}, data={}", key, obj);
                    } else {
                        log.info("redis cache not hit:key={}", key);
                    }
                }
            }
            return obj;
        } catch (Throwable throwable) {
            throw new CacheException(redisCached.name(), redisCached.key(), cachedMethod, throwable);
        }
    }

    public Object get(ProceedingJoinPoint proceedingJoinPoint) {
        try {
            Object[] args = proceedingJoinPoint.getArgs();
            String key = keyParser.generateKey(redisCached.name(), redisCached.key(), cachedMethod, args);
            return this.get(key);
        } catch (Throwable throwable) {
            throw new CacheException(redisCached.name(), redisCached.key(), cachedMethod, throwable);
        }
    }

    public void put(Object[] args, Object obj) {
        try {
            String key = keyParser.generateKey(redisCached.name(), redisCached.key(), cachedMethod, args);
            this.put(key, obj);
        } catch (Throwable throwable) {
            throw new CacheException(redisCached.name(), redisCached.key(), cachedMethod, throwable);
        }
    }

    private Object get(String key) {
        String s = redisTemplate.opsForValue().get(key);
        if (s == null || s.isEmpty()) {
            return s;
        } else {
            return serializer.deserialize(s, cacheReturnType);
        }
    }

    private void put(String key, Object obj) {
        redisTemplate.opsForValue().set(key, serializer.serialize(obj), redisCached.expire(), redisCached.expireTimeUnit());
    }
}
