package com.wikia.calabash.cache;

import com.wikia.calabash.cache.guava.LocalCache;
import com.wikia.calabash.cache.redis.RedisCache;
import lombok.extern.slf4j.Slf4j;
import org.apache.commons.lang3.tuple.Pair;
import org.aspectj.lang.ProceedingJoinPoint;
import org.aspectj.lang.annotation.Around;
import org.aspectj.lang.annotation.Aspect;
import org.aspectj.lang.reflect.MethodSignature;
import org.springframework.stereotype.Component;

import javax.annotation.Resource;
import java.util.List;

@Component
@Aspect
@Slf4j
public class ReloadCacheAspect {
    @Resource
    private CacheManager cacheManager;

    @SuppressWarnings("unchecked")
    @Around("@annotation(ReloadCache)")
    public Object doAround(ProceedingJoinPoint joinPoint) throws Throwable {
        try {
            MethodSignature methodSignature = (MethodSignature) joinPoint.getSignature();
            ReloadCache refreshRedisCache = methodSignature.getMethod().getAnnotation(ReloadCache.class);
            String cacheName = refreshRedisCache.name();

            Object obj = joinPoint.proceed();

            LocalCache localCache = cacheManager.getLocalCache(cacheName);
            if (localCache != null) {
                List<Pair<Object[], Object>> keyValues = (List<Pair<Object[], Object>>) obj;
                for (Pair<Object[], Object> keyValue : keyValues) {
                    localCache.put(keyValue.getKey(), keyValue.getValue());
                }
            }

            RedisCache redisCache = cacheManager.getRedisCache(cacheName);
            if (redisCache != null) {
                List<Pair<Object[], Object>> keyValues = (List<Pair<Object[], Object>>) obj;
                for (Pair<Object[], Object> keyValue : keyValues) {
                    redisCache.put(keyValue.getKey(), keyValue.getValue());
                }
            }

            return obj;
        } catch (Throwable throwable) {
            log.warn("reload cache exception", throwable);
            return joinPoint.proceed();
        }
    }

}