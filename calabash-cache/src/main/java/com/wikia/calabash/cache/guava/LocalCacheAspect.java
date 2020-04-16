package com.wikia.calabash.cache.guava;

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

    @Around("@annotation(LocalCached)")
    public Object doAround(ProceedingJoinPoint joinPoint) throws Throwable {
        try {
            MethodSignature methodSignature = (MethodSignature) joinPoint.getSignature();
            LocalCached localCached = methodSignature.getMethod().getAnnotation(LocalCached.class);
            LocalCache cache = cacheManager.getLocalCache(localCached.name());
            return cache.get(joinPoint.getArgs());
        } catch (Throwable throwable) {
            log.warn("local cache exception", throwable);
            return joinPoint.proceed();
        }
    }
}