package com.wikia.calabash.cache.guava;

import com.wikia.calabash.cache.AnnotationCacheConfig;
import com.wikia.calabash.cache.CacheManager;
import lombok.extern.slf4j.Slf4j;
import org.aspectj.lang.ProceedingJoinPoint;
import org.aspectj.lang.annotation.Around;
import org.aspectj.lang.annotation.Aspect;
import org.aspectj.lang.reflect.MethodSignature;
import org.springframework.core.annotation.Order;
import org.springframework.stereotype.Component;

import javax.annotation.Resource;

@Aspect
@Component
@Slf4j
@Order(1)
public class LocalCacheAspect {
    @Resource
    private CacheManager cacheManager;
    @Resource
    private AnnotationCacheConfig config;

    @Around("@annotation(LocalCached)")
    public Object doAround(ProceedingJoinPoint joinPoint) throws Throwable {
        try {
            if (!config.isEnable()) {
                return joinPoint.proceed();
            }
            MethodSignature methodSignature = (MethodSignature) joinPoint.getSignature();
            LocalCached localCached = methodSignature.getMethod().getAnnotation(LocalCached.class);
            LocalCache cache = cacheManager.getLocalCache(localCached.name());
            return cache.get(joinPoint);
        } catch (Throwable throwable) {
            log.warn("local cache exception", throwable);
            return joinPoint.proceed();
        }
    }
}